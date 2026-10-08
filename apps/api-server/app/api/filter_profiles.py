import asyncio
import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator
from socketio.exceptions import TimeoutError as SocketTimeout

from app.filter_planner import FilterPlanner, clean_options
from app.models.filter_profile import ProfileWrite, ProfileDefinition, StrictModel, FIELD_ORDER
from app.realtime.server import sio
from app.repositories.filter_profiles import FilterProfileRepository, PreflightUnavailable, reserve_options_runner, renew_lease

router = APIRouter(prefix='/filter-profiles', tags=['filter-profiles'])
profiles = FilterProfileRepository()


class OptionsInput(StrictModel):
    runner_id: str = Field(alias='runnerId', min_length=1, max_length=128)
    year: int = Field(ge=1900)
    context: dict = Field(default_factory=dict)

    @field_validator('year')
    @classmethod
    def valid_year(cls, value):
        if value > datetime.now().year:
            raise ValueError('Choose the current calendar year or an earlier year.')
        return value

    @field_validator('context')
    @classmethod
    def valid_context(cls, value):
        allowed = {'delhiNcr', 'states', 'categoryGroups', 'subCategories', 'evTypes'}
        if set(value) - allowed:
            raise ValueError('Unsupported parent filter.')
        for field, selection in value.items():
            if field == 'delhiNcr':
                if not isinstance(selection, str) or not selection or len(selection) > 500:
                    raise ValueError('Invalid State region.')
            elif not isinstance(selection, list) or len(selection) > 100 or any(
                not isinstance(item, str) or not item.strip() or len(item) > 500 for item in selection):
                raise ValueError('Invalid parent selection.')
        return value


class MakerSearchInput(OptionsInput):
    search: str = Field(min_length=1, max_length=500)


async def command(socket_id, request, token):
    try:
        response = await sio.call('runner:options', {**request, 'requestId': token}, to=socket_id, namespace='/runner', timeout=115)
    except SocketTimeout as error:
        raise ValueError('VAHAN options timed out. Retry after the browser worker is ready.') from error
    if not isinstance(response, dict):
        raise ValueError('VAHAN returned an invalid options acknowledgement.')
    if not response.get('ok'):
        if response.get('code') == 'RUNNER_BUSY':
            raise PreflightUnavailable(None,'WORKER_BUSY',
                'The selected worker is finishing another operation. Filter options will retry when it is idle.')
        raise ValueError(response.get('error', 'Could not load live VAHAN options.'))
    options = response.get('options')
    if not isinstance(options, (dict, list)):
        raise ValueError('VAHAN returned an invalid options response.')
    return options


def base_filters(year):
    return {'period': 'CALENDAR YEAR', 'fromYear': str(year), 'toYear': str(year),
            'fromDate': '', 'toDate': '', 'financialYears': [], 'delhiNcr': 'ALL STATES',
            'states': [], 'rtos': [], 'yAxis': 'Maker', 'xAxis': 'Month Wise'}


def http_error(error):
    if isinstance(error,PreflightUnavailable):
        return HTTPException(409,{'code':'PREFLIGHT_WAITING','message':str(error),'retryAfterMs':5000})
    if isinstance(error,ValueError) and str(error).startswith('NETWORK_PAUSED:'):
        return HTTPException(409,{'code':'PREFLIGHT_WAITING','message':str(error),'retryAfterMs':5000})
    return HTTPException(404 if isinstance(error, LookupError) else 409, str(error))


async def compile_profile_plan(profile, runner_id, owner, year, progress):
    """Use the same live validation for previews and unattended scheduled runs."""
    try:
        from app.repositories.ui_contract import require_gate
        await require_gate(owner, [runner_id], fresh=True)
    except ValueError as error:raise http_error(error) from error
    definition = ProfileDefinition.model_validate(profile['definition'])
    year = definition.report.year if definition.report else year
    async with reserve_options_runner(runner_id, owner) as (socket_id, token):
        cache = {}
        async def lookup(field, context, wanted):
            await renew_lease(runner_id, token)
            if field == 'rtos':
                await command(socket_id, {'type': 'GET_STATE_OPTIONS', 'delhiNcr': context['delhiNcr']}, token)
                await renew_lease(runner_id, token)
                return await command(socket_id, {'type': 'GET_RTO_OPTIONS', 'stateLabels': context['states'][0]}, token)
            if field == 'makers':
                if wanted:
                    values = []
                    for value in wanted:
                        await renew_lease(runner_id, token)
                        values.extend(await command(socket_id, {'type': 'SEARCH_MAKERS', 'search': value}, token))
                    return list(dict.fromkeys(values))
                return await command(socket_id, {'type': 'GET_ALL_MAKERS'}, token)
            key = json.dumps(context, sort_keys=True)
            if key not in cache:
                cache[key] = await command(socket_id, {'type': 'GET_FILTER_CONTEXT',
                    'filters': {**base_filters(year), **context}}, token)
            return cache[key].get(field, [])
        plan = await FilterPlanner(definition, year, lookup, progress).compile()
        plan.update(profileId=profile['id'], profileRevision=profile['revision'], profileName=profile['name'])
        return plan


@router.get('')
async def list_profiles(request: Request):
    return await profiles.list(request.state.authenticated_user)


@router.post('')
async def create_profile(command: ProfileWrite, request: Request):
    return await profiles.save(request.state.authenticated_user, command)


@router.put('/{profile_id}')
async def update_profile(profile_id: UUID, command: ProfileWrite, request: Request):
    try:
        return await profiles.save(request.state.authenticated_user, command, profile_id)
    except (LookupError, ValueError) as error:
        raise http_error(error) from error


@router.delete('/{profile_id}')
async def delete_profile(profile_id: UUID, revision: int, request: Request):
    try:
        await profiles.delete(request.state.authenticated_user, profile_id, revision)
        return {'ok': True}
    except (LookupError, ValueError) as error:
        raise http_error(error) from error


@router.post('/options')
async def load_options(command_input: OptionsInput, request: Request):
    try:
        from app.repositories.ui_contract import require_gate
        await require_gate(request.state.authenticated_user, [command_input.runner_id], fresh=True)
        async with reserve_options_runner(command_input.runner_id, request.state.authenticated_user) as (socket_id, token):
            options = await command(socket_id, {'type': 'GET_FILTER_CONTEXT',
                'filters': {**base_filters(command_input.year), **command_input.context}}, token)
            if command_input.context.get('states'):
                rtos = []
                for state in command_input.context['states']:
                    await renew_lease(command_input.runner_id, token)
                    rtos.extend(await command(socket_id, {'type': 'GET_RTO_OPTIONS', 'stateLabels': state}, token))
                options['rtos'] = list(dict.fromkeys(rtos))
            return {field: clean_options(options.get(field, []), field == 'delhiNcr') for field in FIELD_ORDER}
    except ValueError as error:
        raise http_error(error) from error


@router.post('/makers')
async def search_makers(command_input: MakerSearchInput, request: Request):
    try:
        from app.repositories.ui_contract import require_gate
        await require_gate(request.state.authenticated_user, [command_input.runner_id], fresh=True)
        async with reserve_options_runner(command_input.runner_id, request.state.authenticated_user) as (socket_id, token):
            return await command(socket_id, {'type': 'SEARCH_MAKERS', 'search': command_input.search}, token)
    except ValueError as error:
        raise http_error(error) from error


@router.post('/{profile_id}/preview')
async def preview_profile(profile_id: UUID, command_input: OptionsInput, request: Request):
    try:
        profile = await profiles.get(request.state.authenticated_user, profile_id)
    except LookupError as error:
        raise http_error(error) from error
    definition = ProfileDefinition.model_validate(profile['definition'])

    year = definition.report.year if definition.report else command_input.year

    async def stream():
        messages = asyncio.Queue()
        async def progress(message):
            await messages.put({'type': 'progress', 'message': message})
        async def build():
            try:
                plan = await compile_profile_plan(profile, command_input.runner_id,
                    request.state.authenticated_user, year, progress)
                await messages.put({'type': 'ready', 'plan': plan})
            except Exception as error:
                await messages.put({'type': 'error', 'message': str(error)})
        task = asyncio.create_task(build())
        terminal = False
        try:
            while True:
                try:
                    event = await asyncio.wait_for(messages.get(), 10)
                except TimeoutError:
                    event = {'type': 'heartbeat'}
                terminal = event['type'] in {'ready', 'error'}
                yield json.dumps(event, ensure_ascii=False) + '\n'
                if terminal:
                    break
        finally:
            if not terminal:
                task.cancel()
            try:
                if terminal:
                    await asyncio.shield(task)
                else:
                    await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(stream(), media_type='application/x-ndjson', headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-store'})
