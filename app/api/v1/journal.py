from datetime import date, datetime, timedelta
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import get_jwt_identity
from sqlalchemy import func
from app.extensions import db
from app.models.journal import JournalEntry
from app.auth.decorators import login_required
import csv
import io

journal_bp = Blueprint("journal", __name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _auto_pnl(data):
    """Compute pnl_pct and outcome from entry/exit prices if not supplied."""
    entry = data.get("entry_price")
    exit_ = data.get("exit_price")
    direction = (data.get("direction") or "BUY").upper()
    # A legitimate quantity of 0 (e.g. a paper trade with no size) must
    # produce a pnl_amount of 0, not silently be treated as quantity=1 —
    # only missing/unspecified quantity defaults to 1.
    raw_qty = data.get("quantity")
    qty = 1 if raw_qty is None else raw_qty

    if entry and exit_:
        if direction == "BUY":
            pnl_pct = (exit_ - entry) / entry * 100
        else:
            pnl_pct = (entry - exit_) / entry * 100

        if "pnl_pct" not in data or data["pnl_pct"] is None:
            data["pnl_pct"] = round(pnl_pct, 4)

        if "pnl_amount" not in data or data["pnl_amount"] is None:
            if direction == "BUY":
                data["pnl_amount"] = round((exit_ - entry) * qty, 2)
            else:
                data["pnl_amount"] = round((entry - exit_) * qty, 2)

    pnl_amount = data.get("pnl_amount")
    if "outcome" not in data or data["outcome"] is None:
        if pnl_amount is not None:
            if pnl_amount > 0:
                data["outcome"] = "win"
            elif pnl_amount < 0:
                data["outcome"] = "loss"
            else:
                data["outcome"] = "breakeven"

    return data


def _parse_date(val):
    if not val:
        return date.today()
    if isinstance(val, date):
        return val
    return datetime.strptime(val, "%Y-%m-%d").date()


# ── routes ────────────────────────────────────────────────────────────────────

@journal_bp.route("/", methods=["GET"])
@login_required
def list_entries():
    user_id = get_jwt_identity()
    page     = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    outcome  = request.args.get("outcome")
    market   = request.args.get("market")
    date_from = request.args.get("date_from")
    date_to   = request.args.get("date_to")

    q = JournalEntry.query.filter_by(user_id=user_id)

    if outcome:
        q = q.filter(JournalEntry.outcome == outcome)
    if market:
        q = q.filter(JournalEntry.market == market)
    if date_from:
        q = q.filter(JournalEntry.trade_date >= _parse_date(date_from))
    if date_to:
        q = q.filter(JournalEntry.trade_date <= _parse_date(date_to))

    q = q.order_by(JournalEntry.trade_date.desc(), JournalEntry.id.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "entries": [e.to_dict() for e in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
        "per_page": per_page,
    }), 200


@journal_bp.route("/", methods=["POST"])
@login_required
def create_entry():
    user_id = get_jwt_identity()
    data = request.get_json() or {}

    data = _auto_pnl(data)

    entry = JournalEntry(
        user_id=user_id,
        asset_id=data.get("asset_id"),
        trade_date=_parse_date(data.get("trade_date")),
        market=data.get("market"),
        direction=(data.get("direction") or "BUY").upper(),
        timeframe=data.get("timeframe"),
        entry_price=data.get("entry_price"),
        exit_price=data.get("exit_price"),
        quantity=data.get("quantity"),
        stop_loss=data.get("stop_loss"),
        target=data.get("target"),
        outcome=data.get("outcome"),
        pnl_amount=data.get("pnl_amount"),
        pnl_pct=data.get("pnl_pct"),
        emotion_tag=data.get("emotion_tag"),
        setup_tags=data.get("setup_tags") or [],
        notes=data.get("notes"),
        screenshot_url=data.get("screenshot_url"),
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify(entry.to_dict()), 201


@journal_bp.route("/<int:entry_id>", methods=["PUT"])
@login_required
def update_entry(entry_id):
    user_id = get_jwt_identity()
    entry = JournalEntry.query.filter_by(id=entry_id, user_id=user_id).first_or_404()
    data = request.get_json() or {}

    data = _auto_pnl(data)

    fields = [
        "asset_id", "market", "direction", "timeframe",
        "entry_price", "exit_price", "quantity", "stop_loss", "target",
        "outcome", "pnl_amount", "pnl_pct", "emotion_tag", "setup_tags",
        "notes", "screenshot_url",
    ]
    for f in fields:
        if f in data:
            setattr(entry, f, data[f])

    if "trade_date" in data:
        entry.trade_date = _parse_date(data["trade_date"])
    if "direction" in data:
        entry.direction = (data["direction"] or "BUY").upper()

    entry.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(entry.to_dict()), 200


@journal_bp.route("/<int:entry_id>", methods=["DELETE"])
@login_required
def delete_entry(entry_id):
    user_id = get_jwt_identity()
    entry = JournalEntry.query.filter_by(id=entry_id, user_id=user_id).first_or_404()
    db.session.delete(entry)
    db.session.commit()
    return jsonify({"message": "Deleted"}), 200


@journal_bp.route("/stats", methods=["GET"])
@login_required
def stats():
    user_id = get_jwt_identity()
    # Only pull the columns stats actually uses — avoids hydrating full
    # JournalEntry ORM objects (all columns incl. notes/prices/etc.) for
    # what may be thousands of rows.
    entries = (JournalEntry.query
               .filter_by(user_id=user_id)
               .with_entities(JournalEntry.outcome, JournalEntry.pnl_amount,
                               JournalEntry.emotion_tag, JournalEntry.market,
                               JournalEntry.trade_date)
               .all())

    if not entries:
        return jsonify({
            "total_trades": 0, "win_rate": 0, "total_pnl": 0,
            "avg_pnl_per_trade": 0, "best_trade": 0, "worst_trade": 0,
            "avg_win": 0, "avg_loss": 0, "profit_factor": 0,
            "by_emotion": {}, "by_market": {}, "by_day_of_week": {},
        }), 200

    total = len(entries)
    wins   = [e for e in entries if e.outcome == "win"]
    losses = [e for e in entries if e.outcome == "loss"]
    pnls   = [e.pnl_amount for e in entries if e.pnl_amount is not None]

    win_rate = round(len(wins) / total * 100, 1) if total else 0
    total_pnl = round(sum(pnls), 2) if pnls else 0
    avg_pnl   = round(total_pnl / total, 2) if total else 0
    best_trade  = max(pnls) if pnls else 0
    worst_trade = min(pnls) if pnls else 0

    win_pnls  = [e.pnl_amount for e in wins  if e.pnl_amount is not None]
    loss_pnls = [e.pnl_amount for e in losses if e.pnl_amount is not None]
    avg_win  = round(sum(win_pnls)  / len(win_pnls),  2) if win_pnls  else 0
    avg_loss = round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0

    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss   = abs(sum(p for p in pnls if p < 0))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss else (float("inf") if gross_profit else 0)

    # by_emotion
    emotion_map = {}
    for e in entries:
        tag = e.emotion_tag or "unknown"
        if tag not in emotion_map:
            emotion_map[tag] = {"trades": 0, "wins": 0}
        emotion_map[tag]["trades"] += 1
        if e.outcome == "win":
            emotion_map[tag]["wins"] += 1
    by_emotion = {
        tag: {"trades": v["trades"], "win_rate": round(v["wins"] / v["trades"] * 100, 1)}
        for tag, v in emotion_map.items()
    }

    # by_market
    market_map = {}
    for e in entries:
        mkt = e.market or "unknown"
        if mkt not in market_map:
            market_map[mkt] = {"trades": 0, "wins": 0, "pnl": 0}
        market_map[mkt]["trades"] += 1
        if e.outcome == "win":
            market_map[mkt]["wins"] += 1
        if e.pnl_amount is not None:
            market_map[mkt]["pnl"] += e.pnl_amount
    by_market = {
        mkt: {
            "trades": v["trades"],
            "win_rate": round(v["wins"] / v["trades"] * 100, 1),
            "pnl": round(v["pnl"], 2),
        }
        for mkt, v in market_map.items()
    }

    # by_day_of_week
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow_map = {d: {"trades": 0, "wins": 0} for d in day_names}
    for e in entries:
        if e.trade_date:
            dow = day_names[e.trade_date.weekday()]
            dow_map[dow]["trades"] += 1
            if e.outcome == "win":
                dow_map[dow]["wins"] += 1
    by_day_of_week = {
        day: {
            "trades": v["trades"],
            "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0,
        }
        for day, v in dow_map.items()
        if v["trades"] > 0
    }

    return jsonify({
        "total_trades": total,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_pnl_per_trade": avg_pnl,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "by_emotion": by_emotion,
        "by_market": by_market,
        "by_day_of_week": by_day_of_week,
    }), 200


@journal_bp.route("/tax-report", methods=["GET"])
@login_required
def tax_report():
    """
    FY-wise (India) realized-gains breakdown built from the user's own
    JournalEntry history — see app/services/tax/report.py for the
    classification rules and important caveats (this is a convenience
    export, not tax advice or a filing-ready computation).
    Optional ?fy=FY2024-25 filters to a single financial year.
    """
    from app.services.tax.report import build_tax_report

    user_id = get_jwt_identity()
    entries = (JournalEntry.query
               .filter(JournalEntry.user_id == user_id, JournalEntry.pnl_amount.isnot(None))
               .order_by(JournalEntry.trade_date.asc())
               .all())

    report = build_tax_report(entries)

    fy_filter = request.args.get("fy")
    if fy_filter:
        report = {fy_filter: report[fy_filter]} if fy_filter in report else {}

    return jsonify({"report": report, "disclaimer":
        "This is a convenience export built from your own logged journal "
        "entries, not tax advice or a filing-ready computation. All "
        "non-crypto trades are bucketed as short-term (STCG) because this "
        "journal doesn't record separate entry/exit dates to detect a "
        "genuine long-term holding — verify classifications and figures "
        "with a qualified CA before filing."
    }), 200


@journal_bp.route("/tax-report/export/csv", methods=["GET"])
@login_required
def export_tax_report_csv():
    """CSV export of the FY-wise realized-gains report — one row per
    trade, tagged with its FY and tax bucket (crypto_vda/ltcg/stcg), plus
    a per-FY/bucket summary block at the top. Optional ?fy=FY2024-25."""
    from app.services.tax.report import build_tax_report

    user_id = get_jwt_identity()
    entries = (JournalEntry.query
               .filter(JournalEntry.user_id == user_id, JournalEntry.pnl_amount.isnot(None))
               .order_by(JournalEntry.trade_date.asc())
               .all())

    report = build_tax_report(entries)
    fy_filter = request.args.get("fy")
    if fy_filter:
        report = {fy_filter: report[fy_filter]} if fy_filter in report else {}

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["SmartTrade AI — FY-wise Realized Gains (convenience export, not tax advice)"])
    writer.writerow([])

    for fy in sorted(report.keys()):
        data = report[fy]
        writer.writerow([fy])
        writer.writerow(["Bucket", "Trades", "Realized P&L", "Gains", "Losses"])
        for bucket_key, label in (("crypto_vda", "Crypto (flat 30%, Sec 115BBH)"),
                                    ("ltcg", "Equity/Other LTCG (>365 days)"),
                                    ("stcg", "Equity/Other STCG (<=365 days)")):
            b = data[bucket_key]
            writer.writerow([label, b["trades"], b["realized_pnl"], b["gains"], b["losses"]])
        writer.writerow([])
        writer.writerow(["Trade Date", "Symbol", "Market", "Direction", "Entry", "Exit",
                          "Quantity", "P&L", "P&L %", "Tax Bucket"])
        for row in data["entries"]:
            writer.writerow([
                row["trade_date"], row["symbol"], row["market"], row["direction"],
                row["entry_price"], row["exit_price"], row["quantity"],
                row["pnl_amount"], row["pnl_pct"], row["tax_bucket"],
            ])
        writer.writerow([])

    today = datetime.utcnow().strftime("%Y-%m-%d")
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=tax_report_{today}.csv"},
    )
