"""Terminal operator-review errors must not be replayed by automatic recovery."""
VALIDATION_STOP_CODES = (
    'CAPTCHA_REFRESH_LIMIT',
    'CAPTCHA_REJECTION_LIMIT',
    'CAPTCHA_WAIT_TIMEOUT',
)


def requires_operator(error):
    return isinstance(error, str) and any(
        error.startswith(code + ':') for code in VALIDATION_STOP_CODES
    )
