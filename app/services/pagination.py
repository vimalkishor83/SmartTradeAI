"""Small, shared pagination guards for API collection endpoints."""


def bounded_page(value, default=1):
    """Return a safe one-based page number for user-controlled input."""
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return default


def bounded_per_page(value, default=20, maximum=100):
    """Return a safe page size to protect database and response budgets."""
    try:
        return min(max(int(value), 1), maximum)
    except (TypeError, ValueError):
        return min(max(default, 1), maximum)
