"""Generate an on-demand workbook from the main table; never persist export copies."""
import io
import re
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from app.db.schema import MONTH_COLUMNS


def report_title(rows, year, state_search='', rto_search=''):
    offices = {(r['state'], r['rto'], r['rto_code']) for r in rows}
    if len(offices) == 1:
        state, rto, code = next(iter(offices))
        office = rto + (' - ' + code if code else '')
    else:
        states = sorted({r['state'] for r in rows})
        state = states[0] if len(states) == 1 else ('Multiple States' if state_search or rto_search else 'All States')
        office = 'Selected RTOs' if rto_search else 'All RTOs'
    return f'Maker Month Wise Data of {office}, {state} ({year})'


def build_workbook(rows, year, state_search='', rto_search=''):
    title = report_title(rows, year, state_search, rto_search)
    filename = re.sub(r'[\\/*?:"<>|\r\n\t]', '_', title).strip('. ')[:200] + '.xlsx'
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = str(year)
    sheet.merge_cells('A1:Q1')
    sheet['A1'] = title
    sheet['A1'].font = Font(name='Calibri', size=14, bold=True, color='163A5F')
    sheet['A1'].alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    sheet.row_dimensions[1].height = 40
    sheet.merge_cells('A2:Q2')
    sheet['A2'] = f'Month Wise · {len(rows):,} manufacturer rows · Blank: no source data for the month · 0: zero registrations'
    sheet['A2'].font = Font(name='Calibri', size=10, color='61746B')
    sheet['A2'].alignment = Alignment(vertical='center', wrap_text=True)
    sheet.row_dimensions[2].height = 26
    headers = ['S.No', 'STATE', 'RTO', 'RTOCode', 'Maker',
               *[f"{month.upper()}'{str(year)[-2:]}" for month in MONTH_COLUMNS]]
    sheet.append(headers)
    border = Border(bottom=Side(style='thin', color='DAE2DC'), right=Side(style='thin', color='DAE2DC'))
    for col, header in enumerate(headers, 1):
        cell = sheet.cell(3, col, header)
        cell.font = Font(name='Calibri', size=11, bold=True, color='152417')
        cell.fill = PatternFill('solid', fgColor='78AF4A' if col <= 5 else 'FFC900')
        cell.alignment = Alignment(horizontal='left' if 2 <= col <= 5 else 'center', vertical='center')
        cell.border = border
    sheet.row_dimensions[3].height = 28
    for number, row in enumerate(rows, 1):
        values = [number, row['state'], row['rto'], row['rto_code'], row['maker'], *[row[m] for m in MONTH_COLUMNS]]
        sheet.append(values)
        index = number + 3
        sheet.row_dimensions[index].height = 32
        for column, value in enumerate(values, 1):
            cell = sheet.cell(index, column)
            # Source labels must remain text, including a manufacturer beginning with '='.
            if isinstance(value, str):
                cell.data_type = 's'
            elif isinstance(value, int) and value > 999_999_999_999_999:
                cell.value, cell.data_type = str(value), 's'  # Excel has only 15 digits of numeric precision.
            cell.font = Font(name='Calibri', size=11, color='263C2E')
            cell.alignment = Alignment(horizontal='left' if 2 <= column <= 5 else 'center',
                                       vertical='center', wrap_text=True)
            cell.border = border
            if number % 2 == 0:
                cell.fill = PatternFill('solid', fgColor='F5F9F3')
            if column >= 6 and isinstance(cell.value, int):
                cell.number_format = '#,##0'
    for column, width in enumerate([7, 30, 32, 12, 62, *([11] * 12)], 1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.freeze_panes = 'F4'
    sheet.auto_filter.ref = f'A3:Q{len(rows) + 3}'
    sheet.print_title_rows = '1:3'
    sheet.print_options.horizontalCentered = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_area = f'A1:Q{len(rows) + 3}'
    output = io.BytesIO()
    try:
        workbook.save(output)
        return output.getvalue(), filename
    finally:
        workbook.close()
