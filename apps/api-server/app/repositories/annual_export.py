"""Write complete Excel reports incrementally; only a bounded SQL batch stays in RAM."""
import io
import re
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
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


class WorkbookWriter:
    def __init__(self, title, year, count):
        self.filename = re.sub(r'[\\/*?:"<>|\r\n\t]', '_', title).strip('. ')[:200] + '.xlsx'
        self.workbook = Workbook(write_only=True)
        self.sheet = self.workbook.create_sheet(str(year))
        self.count = count
        self.written = 0
        self.border = Border(bottom=Side(style='thin', color='DAE2DC'), right=Side(style='thin', color='DAE2DC'))
        self.font = Font(name='Calibri', size=11, color='263C2E')
        self.text_alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
        self.number_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        self.alt_fill = PatternFill('solid', fgColor='F5F9F3')
        sheet = self.sheet
        sheet.merged_cells.add('A1:Q1'); sheet.merged_cells.add('A2:Q2')
        sheet.row_dimensions[1].height = 40
        sheet.row_dimensions[2].height = 26
        sheet.row_dimensions[3].height = 28
        sheet.sheet_format.defaultRowHeight = 32
        for column, width in enumerate([7,30,32,12,62,*([11]*12)],1):
            sheet.column_dimensions[get_column_letter(column)].width = width
        sheet.freeze_panes = 'F4'
        sheet.auto_filter.ref = f'A3:Q{count+3}'
        sheet.print_title_rows = '1:3'
        sheet.print_options.horizontalCentered = True
        sheet.page_setup.orientation = 'landscape'
        sheet.page_setup.paperSize = Worksheet.PAPERSIZE_A3
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.print_area = f'A1:Q{count+3}'
        heading = WriteOnlyCell(sheet, title)
        heading.font = Font(name='Calibri',size=14,bold=True,color='163A5F')
        heading.alignment = Alignment(horizontal='center',vertical='center',wrap_text=True)
        sheet.append([heading])
        info = WriteOnlyCell(sheet, f'Month Wise · {count:,} manufacturer rows · Blank: no source data for the month · 0: zero registrations')
        info.font = Font(name='Calibri',size=10,color='61746B')
        info.alignment = Alignment(vertical='center',wrap_text=True)
        sheet.append([info])
        headers = ['S.No','STATE','RTO','RTOCode','Maker',*[f"{m.upper()}'{str(year)[-2:]}" for m in MONTH_COLUMNS]]
        cells=[]
        for column,value in enumerate(headers,1):
            cell=WriteOnlyCell(sheet,value)
            cell.font=Font(name='Calibri',size=11,bold=True,color='152417')
            cell.fill=PatternFill('solid',fgColor='78AF4A' if column<=5 else 'FFC900')
            cell.alignment=self.text_alignment if 2<=column<=5 else self.number_alignment
            cell.border=self.border;cells.append(cell)
        sheet.append(cells)

    def append(self, rows):
        for row in rows:
            self.written += 1
            values=[self.written,row['state'],row['rto'],row['rto_code'],row['maker'],*[row[m] for m in MONTH_COLUMNS]]
            cells=[]
            for column,value in enumerate(values,1):
                if isinstance(value,int) and value>999_999_999_999_999:
                    value=str(value)
                cell=WriteOnlyCell(self.sheet,value)
                if isinstance(value,str):cell.data_type='s'
                cell.font=self.font;cell.border=self.border
                cell.alignment=self.text_alignment if 2<=column<=5 else self.number_alignment
                if self.written%2==0:cell.fill=self.alt_fill
                if column>=6 and isinstance(value,int):cell.number_format='#,##0'
                cells.append(cell)
            self.sheet.append(cells)

    def save(self, destination):
        if self.written != self.count:
            raise ValueError('Report row count changed during export.')
        self.workbook.save(destination)
        self.workbook.close()

    def abort(self):
        try:
            if not self.sheet.closed:self.sheet.close()
            if self.sheet._writer:self.sheet._writer.cleanup()
        finally:self.workbook.close()


def build_workbook(rows, year, state_search='', rto_search=''):
    writer=WorkbookWriter(report_title(rows,year,state_search,rto_search),year,len(rows))
    output=io.BytesIO()
    try:
        writer.append(rows);writer.save(output)
        return output.getvalue(),writer.filename
    except BaseException:
        writer.abort();raise
