"""Expand only native valid branches, retaining combined fixed multi-selections."""
import json
import time

from app.models.filter_profile import FIELD_ORDER, FIELD_LABELS, PARENTS, SCALAR_FIELDS, ProfileDefinition, case_key


def labels(value):
    return value if isinstance(value, list) else [value] if value else []


def clean_options(values, allow_all=False):
    import re
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError('VAHAN returned an invalid filter value list. Retry loading options.')
    result, seen = [], set()
    for value in values:
        value = ' '.join(value.split())
        if not value or re.match(r'^(?:[-–—]|select\b|choose\b|any$|both$|none$)', value, re.I) or (not allow_all and re.match(r'^all(?:\s|$)', value, re.I)):
            continue
        if value.casefold() not in seen:
            seen.add(value.casefold()); result.append(value)
    return result


class FilterPlanner:
    def __init__(self, definition: ProfileDefinition, year: int, lookup, progress):
        self.definition, self.year, self.lookup, self.progress = definition, definition.report.year if definition.report else year, lookup, progress
        self.cache, self.scenarios, self.seen = {}, [], set()
        self.skipped = self.explored = 0
        self.plan_bytes = 0
        self.started = time.monotonic()

    def rules_match(self, values):
        for rule in self.definition.rules:
            if rule.when_field not in values or rule.target_field not in values:
                continue
            left = {value.casefold() for value in labels(values[rule.when_field])}
            if not left.intersection(value.strip().casefold() for value in rule.when_values):
                continue
            right = {value.casefold() for value in labels(values[rule.target_field])}
            present = bool(right.intersection(value.strip().casefold() for value in rule.target_values))
            if (rule.action == 'require' and not present) or (rule.action == 'exclude' and present):
                return False
        return True

    async def candidates(self, field, chosen):
        policy = self.definition.fields[field]
        if policy.mode == 'fixed' and not policy.values:
            return [''] if field in SCALAR_FIELDS else [[]]
        context = {parent: chosen[parent] for parent in PARENTS.get(field, ())}
        wanted = policy.values if policy.mode == 'fixed' else policy.include
        key = json.dumps([field, context, wanted], sort_keys=True)
        if key not in self.cache:
            if len(self.cache) >= 160:
                raise ValueError('Too many dependent option contexts. Restrict the parent filters and preview again.')
            await self.progress(f'Checking {FIELD_LABELS[field]} · {len(self.scenarios)} valid cases')
            self.cache[key] = clean_options(await self.lookup(field, context, wanted), field == 'delhiNcr')
        options = self.cache[key]
        by_name = {value.casefold(): value for value in options}
        excluded = {value.casefold() for value in policy.exclude}
        included = {value.casefold() for value in policy.include}
        selected = [by_name[value.casefold()] for value in wanted if value.casefold() in by_name]
        if policy.mode == 'fixed' and field not in ('states', 'rtos'):
            if len(selected) != len(policy.values) or any(value.casefold() in excluded for value in selected):
                self.skipped += 1; return []
            return selected if field in SCALAR_FIELDS else [selected]
        if policy.mode == 'fixed':
            options = selected
        else:
            options = [value for value in options if not included or value.casefold() in included]
        options = [value for value in options if value.casefold() not in excluded]
        if not options:
            self.skipped += 1
        return options if field in SCALAR_FIELDS else [[value] for value in options]

    async def walk(self, position, chosen):
        self.explored += 1
        if self.explored > 100_000 or time.monotonic() - self.started > 600:
            raise ValueError('Preview limit reached. Narrow Include/Exclude conditions and try again.')
        if not self.rules_match(chosen):
            self.skipped += 1; return
        if position < len(FIELD_ORDER):
            field = FIELD_ORDER[position]
            for value in await self.candidates(field, chosen):
                await self.walk(position + 1, {**chosen, field: value})
            return
        filters = {**chosen, 'period': 'CALENDAR YEAR', 'fromYear': str(self.year), 'toYear': str(self.year),
                   'financialYears': [], 'fromDate': '', 'toDate': '', 'yAxis': 'Maker', 'xAxis': 'Month Wise',
                   'autoApply': True, 'autoExport': True}
        identity = case_key(filters)
        if identity in self.seen:
            return
        if len(self.scenarios) >= self.definition.max_cases:
            raise ValueError(f'More than {self.definition.max_cases} valid cases. Restrict filters; no partial run was created.')
        self.plan_bytes += len(json.dumps(filters, ensure_ascii=False).encode()) + 1000
        if self.plan_bytes > 12 * 1024 * 1024:
            raise ValueError('The generated plan is too large. Narrow the filter selections before running.')
        self.seen.add(identity)
        state, rto = chosen['states'][0], chosen['rtos'][0]
        name = f'Maker Month Wise Data of {rto}, {state} ({self.year})'
        variants = [f'{FIELD_LABELS[field]}: {", ".join(labels(chosen[field]))}' for field in FIELD_ORDER
                    if field not in ('states','rtos') and self.definition.fields[field].mode == 'iterate']
        if variants:
            name += ' · ' + ' · '.join(variants)
        self.scenarios.append({'name': name[:500],
            'caseKey': case_key({key: value for key, value in filters.items() if key not in {'fromYear', 'toYear'}}), 'filters': filters})
        if len(self.scenarios) % 100 == 0:
            await self.progress(f'{len(self.scenarios)} valid cases · checking combinations')

    async def compile(self):
        await self.walk(0, {})
        if not self.scenarios:
            raise ValueError('No valid cases match this profile. Check fixed values and combination constraints.')
        return {'year': self.year, 'states': list(dict.fromkeys(case['filters']['states'][0] for case in self.scenarios)),
                'scenarios': self.scenarios, 'skippedBranches': self.skipped}
