import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

function moduleUrl(file, dependencies = {}) {
  let source = readFileSync(new URL(file, import.meta.url), 'utf8');
  for (const [name, url] of Object.entries(dependencies)) source = source.replace(`'${name}'`, `'${url}'`);
  return `data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,
    {compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText).toString('base64')}`;
}
const state = moduleUrl('../src/services/persistent-state.ts', {
  './api-client': 'data:text/javascript,export const api={};export const getAccessToken=()=>null;',
});
const {scheduleDateTime, scheduleDateTimeIso, formatScheduledTime, formatUiDateTime, timeZoneDateKey,
  scheduledDayOfMonth, runTimeZoneLabel} =
  await import(moduleUrl('../src/run-schedules.ts', {'./services/persistent-state':state}));
const vietnam='Asia/Ho_Chi_Minh', india='Asia/Kolkata';
const utc='2026-10-11T17:15:00.000Z';
assert.deepEqual(scheduleDateTime(new Date(utc),vietnam),{date:'2026-10-12',time:'00:15'});
assert.deepEqual(scheduleDateTime(new Date(utc),india),{date:'2026-10-11',time:'22:45'});
assert.equal(new Date(scheduleDateTimeIso('2026-10-12','00:15',vietnam)).toISOString(),utc);
assert.equal(new Date(scheduleDateTimeIso('2026-10-12','00:15',india)).toISOString(),'2026-10-11T18:45:00.000Z');
assert.equal(formatScheduledTime(utc,vietnam),'12 Oct 2026, 00:15');
assert.equal(formatScheduledTime(utc,india),'11 Oct 2026, 22:45');
const midnight='2026-01-01T18:00:00.000Z';
assert.equal(formatUiDateTime(midnight,vietnam),'02/01/2026, 01:00');
assert.equal(formatUiDateTime(midnight,india),'01/01/2026, 23:30');
assert.equal(timeZoneDateKey(midnight,vietnam),'2026-01-02');
assert.equal(timeZoneDateKey(midnight,india),'2026-01-01');
assert.equal(scheduledDayOfMonth('2026-01-31T17:30:00Z',vietnam),1);
assert.equal(scheduledDayOfMonth('2026-01-31T17:30:00Z',india),31);
assert.equal(runTimeZoneLabel(vietnam),'Vietnam time (UTC+07:00)');
assert.equal(runTimeZoneLabel(india),'India time (UTC+05:30)');
console.log('Vietnam/India: UTC date rollover, local date/time round-trip, month boundaries and labels passed.');
