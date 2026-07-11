"""
Thin wrapper around sentry_sdk.capture_exception so call sites don't need
to guard against Sentry being uninitialized (SENTRY_DSN unset — see
app/__init__.py:_init_error_tracking) or the package being unavailable.
Always safe to call; a no-op when Sentry isn't configured.
"""
import logging

logger = logging.getLogger(__name__)


def capture(exc: Exception, **context):
    """Report an exception to Sentry (if configured) with optional extra
    context tags, without ever raising itself — call sites in background
    jobs handling real money (order placement, protective-order close)
    should never have their own error handling disrupted by the reporting
    call failing."""
    try:
        import sentry_sdk
        if context:
            with sentry_sdk.push_scope() as scope:
                for k, v in context.items():
                    scope.set_extra(k, v)
                sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass  # Sentry not configured/available — the caller's own logger.error already fired
