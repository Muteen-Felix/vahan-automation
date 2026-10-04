from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ReportRow(BaseModel):
    section: Literal['head', 'body', 'foot']
    cells: list[str] = Field(min_length=1, max_length=1000)
    spans: list[dict[str, int]] = Field(default_factory=list, max_length=1000)


class ReportTable(BaseModel):
    id: str = Field(default='', max_length=512)
    caption: str = Field(default='', max_length=8000)
    rows: list[ReportRow] = Field(min_length=1, max_length=100_000)


class ReportResultRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    result: Literal['DATA', 'NO_RECORD']
    message: str = Field(max_length=240)
    observed_at: AwareDatetime = Field(alias='observedAt')
    page_url: str = Field(alias='pageUrl', max_length=2048)
    tables: list[ReportTable] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def validate_result(self):
        if self.result == 'NO_RECORD':
            if self.message != 'No record found' or self.tables:
                raise ValueError('No-data requires No record found and no data tables.')
        elif not any(row.section == 'body' and any(row.cells)
                     for table in self.tables for row in table.rows):
            raise ValueError('Data result requires table body rows.')
        if sum(len(table.rows) for table in self.tables) > 100_000:
            raise ValueError('Report exceeds 100,000 DOM rows.')
        return self
