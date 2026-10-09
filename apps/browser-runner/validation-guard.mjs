// A job's operator-validation budget survives challenge IDs and refreshes.
// This module never recognizes an image, refreshes a page or submits a form.
export const VALIDATION_LIMITS = Object.freeze({refreshes: 10, rejections: 3, waitMs: 10 * 60_000});
export const VALIDATION_STOP_CODES = Object.freeze([
  'CAPTCHA_REFRESH_LIMIT', 'CAPTCHA_REJECTION_LIMIT', 'CAPTCHA_WAIT_TIMEOUT',
]);

export function isValidationStop(value) {
  const message = typeof value === 'string' ? value : value?.message;
  return typeof message === 'string' && VALIDATION_STOP_CODES.some(code => message.startsWith(code + ':'));
}

function stopped(code, detail) {
  return Object.assign(new Error(`${code}: ${detail} Operator review is required; automatic retries are stopped.`), {code});
}

export function createValidationGuard(onTimeout, {
  now = () => Date.now(), schedule = setTimeout, unschedule = clearTimeout,
} = {}) {
  let deadline = null, refreshes = 0, rejections = 0, timer, generation = 0, stopError;

  function trip(code, detail) {
    stopWaiting();
    return stopError ||= stopped(code, detail);
  }

  function check() {
    if (stopError) throw stopError;
    if (deadline === null) deadline = now() + VALIDATION_LIMITS.waitMs;
    if (now() >= deadline) throw trip('CAPTCHA_WAIT_TIMEOUT', 'Validation has exceeded its 10-minute waiting deadline.');
  }

  function stopWaiting() {
    generation++;
    if (timer !== undefined) unschedule(timer);
    timer = undefined;
  }

  function wait() {
    stopWaiting();
    check();
    const expected = generation;
    timer = schedule(() => {
      if (generation !== expected) return;
      timer = undefined;
      onTimeout(trip('CAPTCHA_WAIT_TIMEOUT', 'Validation has exceeded its 10-minute waiting deadline.'));
    }, deadline - now());
    timer?.unref?.();
  }

  function refresh() {
    check();
    if (refreshes >= VALIDATION_LIMITS.refreshes) {
      throw trip('CAPTCHA_REFRESH_LIMIT', 'The job has already used its 10 permitted refreshes.');
    }
    refreshes++;
  }

  function rejected() {
    stopWaiting();
    check();
    rejections++;
    if (rejections >= VALIDATION_LIMITS.rejections) {
      throw trip('CAPTCHA_REJECTION_LIMIT', 'Validation was rejected three times.');
    }
  }

  return {check, wait, refresh, rejected, stopWaiting};
}
