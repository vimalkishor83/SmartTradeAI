"""
Daily Compound Calculator — internal, super-admin-only utility.

Reimplements the standalone "Daily Compound Calculator" Flutter app (its
source is lost; see
D:\\Claude\\Documentation\\daily_compound_calculator_Documentation for the
surviving spec this was built from) as a page + small API inside
SmartTrade AI, so a super admin can model compound-interest scenarios and
save them, shared across admins via the database instead of one device's
local SQLite file.

Deliberately self-contained in one new file/module rather than touching
app/views.py or app/api/v1/admin.py — this defines its own Blueprint with
both the page route and its JSON API routes, and its own super-admin page
gate (mirroring app.auth.decorators.page_admin_required's pattern but
checking is_super_admin instead of the admin role), so wiring this in
only requires two additive lines elsewhere: importing and registering
this blueprint in app/__init__.py, and importing the model in
app/models/__init__.py so Alembic/SQLAlchemy see it.
"""
from __future__ import annotations

from datetime import date, datetime
from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from app.auth.decorators import super_admin_required
from app.extensions import db
from app.models.daily_compound_calculator import DailyCompoundCalculation
from app.models.user import User
from app.services.daily_compound.engine import (
    VALID_DURATION_UNITS,
    VALID_FREQUENCIES,
    calculate,
)

daily_compound_bp = Blueprint("daily_compound_calculator", __name__)


def _page_super_admin_required(f):
    """Page-route equivalent of @super_admin_required — redirects a
    browser navigation instead of returning a JSON 401/403, matching
    app.auth.decorators.page_admin_required's own rationale (that
    decorator gates on the "admin" role, not specifically
    is_super_admin, so it doesn't fit this page)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            verify_jwt_in_request()
        except Exception:
            return redirect(url_for("views.login"))

        user_id = get_jwt_identity()
        user = User.query.get(int(user_id)) if user_id else None
        if not user or not user.is_active or not user.is_super_admin:
            return redirect(url_for("views.dashboard"))

        return f(*args, **kwargs)
    return decorated


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _run_calculation_from_payload(data: dict):
    """Shared input parsing for /calculate and /saved — raises ValueError
    with a user-facing message on bad input, translated to a 400 by each
    route's own except block."""
    try:
        principal = float(data["principal"])
        rate_percent = float(data["rate_percent"])
        start_date = _parse_date(data["start_date"])
        duration_value = int(data["duration_value"])
        duration_unit = str(data["duration_unit"])
        frequency = str(data["frequency"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"Invalid or missing input: {e}")

    max_integer_digits = int(data.get("max_integer_digits", 20))

    result = calculate(
        principal=principal,
        rate_percent=rate_percent,
        start_date=start_date,
        duration_value=duration_value,
        duration_unit=duration_unit,
        frequency=frequency,
        max_integer_digits=max_integer_digits,
    )
    return result, {
        "principal": principal, "rate_percent": rate_percent, "start_date": start_date,
        "duration_value": duration_value, "duration_unit": duration_unit, "frequency": frequency,
    }


# ─── Page ────────────────────────────────────────────────────────────
@daily_compound_bp.route("/admin/daily-compound-calculator")
@_page_super_admin_required
def page():
    return render_template(
        "admin/daily_compound_calculator.html",
        duration_units=sorted(VALID_DURATION_UNITS),
        frequencies=sorted(VALID_FREQUENCIES),
    )


# ─── API ─────────────────────────────────────────────────────────────
@daily_compound_bp.route("/api/v1/daily-compound-calculator/calculate", methods=["POST"])
@super_admin_required
def api_calculate():
    data = request.get_json(silent=True) or {}
    try:
        result, _ = _run_calculation_from_payload(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result.to_dict()), 200


@daily_compound_bp.route("/api/v1/daily-compound-calculator/saved", methods=["GET"])
@super_admin_required
def api_list_saved():
    rows = DailyCompoundCalculation.query.order_by(
        DailyCompoundCalculation.updated_at.desc()
    ).all()
    return jsonify({"saved": [r.to_dict() for r in rows]}), 200


@daily_compound_bp.route("/api/v1/daily-compound-calculator/saved", methods=["POST"])
@super_admin_required
def api_save():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    try:
        _, inputs = _run_calculation_from_payload(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    user_id = int(get_jwt_identity())
    existing = DailyCompoundCalculation.query.filter(
        db.func.lower(DailyCompoundCalculation.name) == name.lower()
    ).first()

    if existing:
        existing.principal = inputs["principal"]
        existing.rate_percent = inputs["rate_percent"]
        existing.start_date = inputs["start_date"]
        existing.duration_value = inputs["duration_value"]
        existing.duration_unit = inputs["duration_unit"]
        existing.frequency = inputs["frequency"]
        row = existing
    else:
        row = DailyCompoundCalculation(
            name=name,
            principal=inputs["principal"],
            rate_percent=inputs["rate_percent"],
            start_date=inputs["start_date"],
            duration_value=inputs["duration_value"],
            duration_unit=inputs["duration_unit"],
            frequency=inputs["frequency"],
            created_by_user_id=user_id,
        )
        db.session.add(row)

    db.session.commit()
    return jsonify(row.to_dict()), 200


@daily_compound_bp.route("/api/v1/daily-compound-calculator/saved/<int:calc_id>", methods=["GET"])
@super_admin_required
def api_get_saved(calc_id):
    row = DailyCompoundCalculation.query.get_or_404(calc_id)
    result = calculate(
        principal=row.principal, rate_percent=row.rate_percent, start_date=row.start_date,
        duration_value=row.duration_value, duration_unit=row.duration_unit, frequency=row.frequency,
    )
    payload = row.to_dict()
    payload["result"] = result.to_dict()
    return jsonify(payload), 200


@daily_compound_bp.route("/api/v1/daily-compound-calculator/saved/<int:calc_id>", methods=["DELETE"])
@super_admin_required
def api_delete_saved(calc_id):
    row = DailyCompoundCalculation.query.get_or_404(calc_id)
    db.session.delete(row)
    db.session.commit()
    return jsonify({"deleted": calc_id}), 200
