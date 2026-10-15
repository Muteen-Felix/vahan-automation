from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


CONTROL_SELECTORS = {
    'archivedFlags': '#archivedFlags', 'period': '#reportType', 'financialYears': '#financialYearSelect',
    'reportYear': '#reportYear', 'reportMonth': '#reportMonth', 'delhiNcr': '#delhiNcr',
    'states': '#stateName', 'rtos': '#rtoCode', 'categoryGroups': '#vehicleCategoryGroup',
    'subCategories': '#vehicleSubCategory', 'classes': '#vehicleClass', 'fuels': '#vehicleFuel',
    'evTypes': '#evType', 'statuses': '#vehicleStatus', 'ownerTypes': '#vehicleOwnerType',
    'vehicleType': '#vehicleType', 'fitness': '#fitnessCheck', 'emissions': '#vehicleEmission',
    'makers': '#vehicleMaker', 'yAxis': '#yAxis', 'xAxis': '#xAxis',
    'fromYear': '#fromYear', 'toYear': '#toYear', 'fromDate': '#fromDate', 'toDate': '#toDate',
    'xAxis_hidden': '#xAxis_hidden',
}
INPUT_FIELDS = {'fromYear', 'toYear', 'fromDate', 'toDate'}


class FilterCheck(BaseModel):
    field: str = Field(max_length=128)
    selector: str = Field(max_length=128)
    expected: list[str] = Field(max_length=1000)
    actual: list[str] = Field(max_length=1000)
    match: bool
    mode: Literal['requested', 'reset', 'hidden']


class FilterExecution(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: Literal['parallel-fill-v1', 'sequential-mutation-v2']
    checks: list[FilterCheck] = Field(min_length=1, max_length=128)
    field_count: int = Field(alias='fieldCount', ge=1, le=128)
    validated_at: AwareDatetime = Field(alias='validatedAt')
    verification_ms: float = Field(alias='verificationMs', ge=0)
    duration_ms: float | None = Field(default=None, alias='durationMs', ge=0)
    groups: list[dict] = Field(default_factory=list, max_length=16)
    repair_passes: int = Field(default=0, alias='repairPasses', ge=0, le=2)

    @model_validator(mode='after')
    def complete_checks(self):
        if self.field_count != len(self.checks) or len({check.field for check in self.checks}) != len(self.checks):
            raise ValueError('Filter checks must be complete and unique.')
        if not all(check.match and CONTROL_SELECTORS.get(check.field) == check.selector for check in self.checks):
            raise ValueError('A filter control is missing or does not match.')
        return self


def validate_against_job(execution: FilterExecution, filters):
    """A runner cannot omit a requested field or verify a different case."""
    checks = {check.field: check for check in execution.checks}
    normalize = lambda value: ' '.join(str(value).split()).casefold()
    for field, value in filters.runner_payload().items():
        if field in {'autoApply', 'autoExport'}:
            continue
        if field not in CONTROL_SELECTORS or field not in checks:
            raise ValueError(f'FILTER_CHECK_INCOMPLETE: {field}.')
        if field in INPUT_FIELDS:
            expected = [str(value or '')]
        elif isinstance(value, list):
            expected = [str(item).strip() for item in value if str(item).strip()]
        else:
            expected = [str(value).strip()] if str(value).strip() else []
        check = checks[field]
        if sorted(map(normalize, expected)) != sorted(map(normalize, check.expected)):
            raise ValueError(f'FILTER_CHECK_WRONG_CASE: {field}.')
        if expected and sorted(map(normalize, expected)) != sorted(map(normalize, check.actual)):
            raise ValueError(f'FILTER_CHECK_MISMATCH: {field}.')
