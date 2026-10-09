import assert from 'node:assert/strict';
import {createValidationGuard, VALIDATION_LIMITS} from './validation-guard.mjs';

function fixture() {
  let time = 0, sequence = 0;
  const timers = new Map(), errors = [];
  const guard = createValidationGuard(error => errors.push(error), {
    now: () => time,
    schedule: (callback, delay) => {const id = ++sequence; timers.set(id, {callback, due: time + delay}); return id;},
    unschedule: id => timers.delete(id),
  });
  return {guard, errors, timers, setTime: value => {time = value;},
    tick: value => {time = value; for (const [id, timer] of [...timers]) {
      if (timer.due <= time) {timers.delete(id); timer.callback();}
    }}};
}

const refresh = fixture();
refresh.guard.wait();
for (let i = 0; i < VALIDATION_LIMITS.refreshes; i++) {
  refresh.guard.refresh();
  refresh.guard.wait(); // New challenge IDs do not create a new budget.
}
assert.throws(() => refresh.guard.refresh(), {code: 'CAPTCHA_REFRESH_LIMIT'});
assert.equal(refresh.timers.size, 0);
assert.throws(() => refresh.guard.check(), {code: 'CAPTCHA_REFRESH_LIMIT'}, 'a stopped job cannot submit while failure is being persisted');
assert.throws(() => refresh.guard.wait(), {code: 'CAPTCHA_REFRESH_LIMIT'}, 'another challenge cannot clear a tripped guard');

const rejected = fixture();
rejected.guard.wait();
for (let i = 1; i < VALIDATION_LIMITS.rejections; i++) {
  rejected.guard.rejected(); rejected.guard.wait();
}
assert.throws(() => rejected.guard.rejected(), {code: 'CAPTCHA_REJECTION_LIMIT'});
assert.equal(rejected.timers.size, 0);

const timeout = fixture();
timeout.guard.wait();
timeout.tick(VALIDATION_LIMITS.waitMs - 1);
assert.equal(timeout.errors.length, 0);
timeout.guard.refresh(); timeout.guard.wait();
timeout.tick(VALIDATION_LIMITS.waitMs);
assert.equal(timeout.errors.length, 1);
assert.equal(timeout.errors[0].code, 'CAPTCHA_WAIT_TIMEOUT');
assert.throws(() => timeout.guard.check(), {code: 'CAPTCHA_WAIT_TIMEOUT'});
timeout.tick(VALIDATION_LIMITS.waitMs * 2);
assert.equal(timeout.errors.length, 1, 'expiry is reported once');

const processing = fixture();
processing.guard.wait();
processing.guard.stopWaiting();
processing.tick(VALIDATION_LIMITS.waitMs + 1);
assert.equal(processing.errors.length, 0, 'waiting timers cannot fail a submitted/result-saving job');
assert.throws(() => processing.guard.wait(), {code: 'CAPTCHA_WAIT_TIMEOUT'}, 'a later wait does not reset the job deadline');

const cancelled = fixture();
cancelled.guard.wait();
const queuedTimer = [...cancelled.timers.values()][0];
cancelled.guard.stopWaiting();
queuedTimer.callback();
assert.equal(cancelled.errors.length, 0, 'an already queued callback is fenced after cancel/fail/stop');

const stale = fixture();
stale.guard.wait();
const oldTimer = [...stale.timers.values()][0];
stale.setTime(100);
stale.guard.wait(); oldTimer.callback();
assert.equal(stale.errors.length, 0, 're-arming fences the old callback while retaining the original deadline');
stale.tick(VALIDATION_LIMITS.waitMs);
assert.equal(stale.errors.length, 1);

console.log('Validation guard: refresh/rejection limits, fixed deadline, processing/cancel cleanup and stale timer fencing passed.');
