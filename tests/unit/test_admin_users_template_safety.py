"""Contract checks for database values rendered by admin User Management."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "admin" / "users.html"


def test_user_values_are_escaped_and_username_is_not_embedded_in_javascript():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "${u.username}" not in source
    assert "${u.email}" not in source
    assert "${u.role || '—'}" not in source
    assert "${u.subscription || '—'}" not in source
    assert "deleteUser(${u.id}, '${u.username}')" not in source
    assert 'data-username="${STSafe.html(u.username)}"' in source
    assert "STSafe.html(u.email)" in source
    assert "STSafe.html(u.role || '—')" in source


def test_user_actions_are_bound_from_dataset_values():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onchange=" not in source
    assert "data-user-action=\"delete-user\"" in source
    assert "data-user-action=\"edit-user\"" in source
    assert "data-user-action=\"toggle-user\"" in source
    assert "data-user-action=\"change-role\"" in source
    assert "data-user-action=\"change-subscription\"" in source
    assert "data-user-action=\"approve-user\"" in source
    assert "data-user-action=\"reject-user\"" in source
    assert "data-user-page=\"${i}\"" in source
    assert "button.addEventListener('click', () => deleteUser" in source
    assert "button.addEventListener('click', () => openEditUser" in source
    assert "button.addEventListener('click', () => toggleUser" in source
    assert "button.addEventListener('change', () => changeUserRole" in source
    assert "button.addEventListener('change', () => changeUserSubscription" in source
