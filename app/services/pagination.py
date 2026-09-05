"""Small, shared pagination guards for API collection endpoints."""


def bounded_int(value, default=1, minimum=1, maximum=None):
    """Return a safe bounded integer for user-controlled query input."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    result = max(result, minimum)
    return min(result, maximum) if maximum is not None else result


def bounded_float(value, default=0.0, minimum=None, maximum=None):
    """Return a safe bounded finite float for query filters."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    if minimum is not None:
        result = max(result, minimum)
    return min(result, maximum) if maximum is not None else result


def bounded_page(value, default=1):
    """Return a safe one-based page number for user-controlled input."""
    return bounded_int(value, default=default, minimum=1)


def bounded_per_page(value, default=20, maximum=100):
    """Return a safe page size to protect database and response budgets."""
    return bounded_int(value, default=default, minimum=1, maximum=maximum)
