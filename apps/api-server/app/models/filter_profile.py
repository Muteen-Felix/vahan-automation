"""Versioned, bounded filter definitions for the existing Maker/Month Wise output."""
from datetime import datetime
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FIELD_ORDER = ('delhiNcr', 'states', 'rtos', 'categoryGroups', 'subCategories', 'classes',
               'evTypes', 'fuels', 'archivedFlags', 'emissions', 'makers', 'statuses',
               'ownerTypes', 'vehicleType', 'fitness')
SCALAR_FIELDS = {'delhiNcr', 'vehicleType', 'fitness'}
FIELD_LABELS = {'delhiNcr':'State region','states':'State','rtos':'RTO','categoryGroups':'Category group',
    'subCategories':'Sub-category','classes':'Class','evTypes':'EV type','fuels':'Fuel',
    'archivedFlags':'Active / Archive','emissions':'Emission','makers':'Maker','statuses':'Status',
    'ownerTypes':'Owner type','vehicleType':'Vehicle type','fitness':'Fitness'}
PARENTS = {'states': ('delhiNcr',), 'rtos': ('delhiNcr', 'states'),
           'subCategories': ('categoryGroups',), 'classes': ('categoryGroups', 'subCategories'),
           'fuels': ('evTypes',)}


def canonical_filters(filters: dict) -> str:
    def clean(value):
        if isinstance(value, list):
            return sorted(set(' '.join(str(item).split()).casefold() for item in value))
        return ' '.join(value.split()).casefold() if isinstance(value, str) else value
    return json.dumps({key: clean(value) for key, value in filters.items()
                       if key not in {'autoApply', 'autoExport'} and clean(value) not in (None, '', [])},
                      sort_keys=True, separators=(',', ':'))


def case_key(filters: dict) -> str:
    return hashlib.sha256(canonical_filters(filters).encode()).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)


class FilterPolicy(StrictModel):
    mode: Literal['fixed', 'iterate'] = 'fixed'
    values: list[str] = Field(default_factory=list, max_length=100)
    include: list[str] = Field(default_factory=list, max_length=100)
    exclude: list[str] = Field(default_factory=list, max_length=500)

    @field_validator('values', 'include', 'exclude')
    @classmethod
    def labels(cls, values):
        result, seen = [], set()
        for value in values:
            value = ' '.join(value.split())
            if not value or len(value) > 500:
                raise ValueError('Filter values must contain 1–500 characters.')
            if value.casefold() not in seen:
                result.append(value); seen.add(value.casefold())
        return result


class CombinationRule(StrictModel):
    when_field: str = Field(alias='whenField')
    when_values: list[str] = Field(alias='whenValues', min_length=1, max_length=100)
    target_field: str = Field(alias='targetField')
    target_values: list[str] = Field(alias='targetValues', min_length=1, max_length=100)
    action: Literal['require', 'exclude'] = 'exclude'

    @model_validator(mode='after')
    def valid_fields(self):
        if self.when_field not in FIELD_ORDER or self.target_field not in FIELD_ORDER:
            raise ValueError('A combination rule contains an unsupported field.')
        if self.when_field == self.target_field:
            raise ValueError('Use Include/Exclude for a constraint on the same field.')
        if any(not value.strip() or len(value) > 500 for value in self.when_values + self.target_values):
            raise ValueError('Rule values must contain 1–500 characters.')
        return self


class ReportSettings(StrictModel):
    year: int = Field(ge=1900, strict=True)
    period: Literal['CALENDAR YEAR'] = 'CALENDAR YEAR'
    y_axis: Literal['Maker'] = Field(default='Maker', alias='yAxis')
    x_axis: Literal['Month Wise'] = Field(default='Month Wise', alias='xAxis')

    @field_validator('year')
    @classmethod
    def valid_year(cls, value):
        if value > datetime.now().year:
            raise ValueError('Choose the current calendar year or an earlier year.')
        return value


class ProfileDefinition(StrictModel):
    version: Literal[1] = 1
    report: ReportSettings | None = None
    fields: dict[str, FilterPolicy]
    rules: list[CombinationRule] = Field(default_factory=list, max_length=30)
    max_cases: int = Field(default=3000, alias='maxCases', ge=1, le=3000, strict=True)

    @model_validator(mode='after')
    def valid_fields(self):
        if set(self.fields) - set(FIELD_ORDER):
            raise ValueError('The profile contains unsupported fields.')
        for field in FIELD_ORDER:
            self.fields.setdefault(field, FilterPolicy())
        for field in SCALAR_FIELDS:
            if self.fields[field].mode == 'fixed' and len(self.fields[field].values) > 1:
                raise ValueError(f'{field} allows one fixed value.')
        for field in ('states', 'rtos', 'archivedFlags'):
            if self.fields[field].mode == 'fixed' and not self.fields[field].values:
                raise ValueError(f'Choose {field} or enable Iterate all.')
        if self.fields['delhiNcr'].mode == 'fixed' and not self.fields['delhiNcr'].values:
            raise ValueError('Choose a State region.')
        for rule in self.rules:
            for field in (rule.when_field, rule.target_field):
                if self.fields[field].mode == 'fixed' and not self.fields[field].values:
                    raise ValueError(f'Rule field {field} must have a selection or use Iterate all.')
        return self


class ProfileWrite(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    definition: ProfileDefinition
    revision: int | None = Field(default=None, ge=1, strict=True)

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Enter a profile name.')
        return value
