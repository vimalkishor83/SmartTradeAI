from pathlib import Path


ROOT = Path(__file__).parents[2]
USERS_TEMPLATE = ROOT / "frontend" / "templates" / "admin" / "users.html"


def test_admin_user_forms_do_not_look_like_saved_login_forms():
    source = USERS_TEMPLATE.read_text(encoding="utf-8")

    for form_id in ("createUserForm", "editUserForm"):
        form_start = source.index(f'<form id="{form_id}"')
        form_end = source.index("</form>", form_start)
        form = source[form_start:form_end]

        assert 'autocomplete="off"' in form
        assert 'data-form-type="other"' in form
        assert 'data-lpignore="true"' in form
        assert 'data-1p-ignore="true"' in form
        assert 'data-bwignore="true"' in form

    assert '<input type="password" class="form-control" id="cuPassword"' in source
    assert '<input type="password" class="form-control" id="euPassword"' in source
    assert source.count('autocomplete="new-password"') == 2
    assert 'id="cuPassword" required />' not in source
    assert 'id="euPassword" placeholder="Leave blank to keep current password" />' not in source
