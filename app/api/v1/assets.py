import math
import re

from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError
from app.models.asset import Asset
from app.extensions import db, cache, limiter
from app.auth.decorators import login_required, admin_required, super_admin_required, premium_required, subscription_feature_required
from app.services.data.fetcher import market_fetcher

assets_bp = Blueprint("assets", __name__)


@assets_bp.route("/", methods=["GET"])
@login_required
def list_assets():
    market = request.args.get("market")

    # Admin-only escape hatch so the Platform Config / Assets admin UI can
    # see and re-enable currently-disabled assets, which are otherwise
    # invisible everywhere (this same query is what every asset picker in
    # the app uses). Bypasses the cache entirely — this path is rare
    # (admin screens only) so freshness matters more than the 300s cache.
    include_inactive = request.args.get("include_inactive") == "1"
    if include_inactive:
        from app.auth.decorators import get_current_user
        user = get_current_user()
        if not user or user.role.name != "admin":
            return jsonify({"error": "Admin access required"}), 403
        query = Asset.query
        if market:
            query = query.filter_by(market=market)
        assets = query.order_by(Asset.market, Asset.symbol).all()
        return jsonify({"assets": [a.to_dict() for a in assets]}), 200

    cache_key = f"assets_list_{market or 'all'}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached), 200

    query = Asset.query.filter_by(is_active=True)
    if market:
        query = query.filter_by(market=market)
    assets = query.order_by(Asset.market, Asset.symbol).all()
    result = {"assets": [a.to_dict() for a in assets]}
    cache.set(cache_key, result, timeout=300)
    return jsonify(result), 200


@assets_bp.route("/<int:asset_id>", methods=["GET"])
@login_required
def get_asset(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    return jsonify(asset.to_dict()), 200


@assets_bp.route("/<int:asset_id>/ticker", methods=["GET"])
@login_required
@limiter.exempt
def get_ticker(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    ticker = market_fetcher.fetch_ticker(asset)
    if not ticker:
        return jsonify({"error": "Ticker data unavailable"}), 503
    return jsonify(ticker), 200


#: Explicit whitelist of client-settable fields — using hasattr(Asset, k)
#: against arbitrary client JSON keys would let a caller set internal
#: columns (id, created_at) or anything else that happens to share a name
#: with a model attribute.
_ASSET_EDITABLE_FIELDS = [
    "symbol", "name", "market", "exchange", "base_currency", "quote_currency",
    "is_active", "data_source", "pip_size", "lot_size", "min_lot",
]

_ASSET_TEXT_LIMITS = {
    "symbol": 30,
    "name": 100,
    "exchange": 50,
    "base_currency": 10,
    "quote_currency": 10,
    "data_source": 50,
    "source": 30,
    "market": 30,
}
_ASSET_SYMBOL_RE = re.compile(r"^[A-Za-z0-9^][A-Za-z0-9.^=_-]{0,29}$")
_ASSET_NUMBER_LIMITS = {
    "pip_size": (0.0, 1_000_000_000_000.0),
    "lot_size": (0.0, 1_000_000_000_000.0),
    "min_lot": (0.0, 1_000_000_000_000.0),
}


def _asset_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, jsonify({"error": "request body must be a JSON object"}), 400
    return data, None, None


def _asset_text(data, field, *, required=False, uppercase=False):
    if field not in data:
        if required:
            raise ValueError(f"{field} is required")
        return None
    value = data[field]
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field} is required")
    if len(value) > _ASSET_TEXT_LIMITS[field]:
        raise ValueError(f"{field} must be {_ASSET_TEXT_LIMITS[field]} characters or fewer")
    if field == "symbol" and value and not _ASSET_SYMBOL_RE.fullmatch(value):
        raise ValueError("symbol contains unsupported characters")
    return value.upper() if uppercase else value


def _asset_number(data, field):
    if field not in data:
        return None
    value = data[field]
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field} must be a number")
    minimum, maximum = _ASSET_NUMBER_LIMITS[field]
    if not math.isfinite(parsed) or parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be finite and between {minimum:g} and {maximum:g}")
    return parsed


def _normalize_asset_fields(data, *, required=False):
    values = {
        "symbol": _asset_text(data, "symbol", required=required, uppercase=True),
        "name": _asset_text(data, "name", required=required),
        "exchange": _asset_text(data, "exchange"),
        "base_currency": _asset_text(data, "base_currency", uppercase=True),
        "quote_currency": _asset_text(data, "quote_currency", uppercase=True),
        "data_source": _asset_text(data, "data_source"),
    }
    values.update({field: _asset_number(data, field) for field in _ASSET_NUMBER_LIMITS})
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            raise ValueError("is_active must be a boolean")
        values["is_active"] = data["is_active"]
    return {field: value for field, value in values.items() if value is not None}


@assets_bp.route("/", methods=["POST"])
@super_admin_required
def create_asset():
    data, error, status = _asset_body()
    if error:
        return error, status
    try:
        values = _normalize_asset_fields(data, required=True)
        market = data.get("market")
        if not isinstance(market, str) or market.strip() not in Asset.MARKETS:
            raise ValueError(f"market must be one of {Asset.MARKETS}")
        values["market"] = market.strip()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    existing = Asset.query.filter_by(
        symbol=values["symbol"], exchange=values.get("exchange")
    ).first()
    if existing:
        return jsonify({"error": f"Asset '{values['symbol']}' already exists for this exchange"}), 409

    asset = Asset(**{k: values[k] for k in values if k in _ASSET_EDITABLE_FIELDS})
    db.session.add(asset)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "An asset with this symbol and exchange already exists"}), 409
    # list_assets caches under f"assets_list_{market or 'all'}" — deleting the
    # bare "assets_list" key (as this did) matched nothing, so a newly created
    # asset stayed invisible until the entry aged out on its own. Sweep every
    # market key the same way delete_asset does.
    for mk in Asset.MARKETS + ["all"]:
        cache.delete(f"assets_list_{mk}")
    return jsonify(asset.to_dict()), 201


@assets_bp.route("/<int:asset_id>", methods=["PUT"])
@super_admin_required
def update_asset(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    data, error, status = _asset_body()
    if error:
        return error, status
    try:
        values = _normalize_asset_fields(data)
        if "market" in data:
            market = data["market"]
            if not isinstance(market, str) or market.strip() not in Asset.MARKETS:
                raise ValueError(f"market must be one of {Asset.MARKETS}")
            values["market"] = market.strip()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not values:
        return jsonify({"error": "no editable fields supplied"}), 400
    if "symbol" in values or "exchange" in values:
        duplicate = Asset.query.filter(
            Asset.id != asset.id,
            Asset.symbol == values.get("symbol", asset.symbol),
            Asset.exchange == values.get("exchange", asset.exchange),
        ).first()
        if duplicate:
            return jsonify({"error": "An asset with this symbol and exchange already exists"}), 409

    for k, v in values.items():
        if k in _ASSET_EDITABLE_FIELDS:
            setattr(asset, k, v)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "An asset with this symbol and exchange already exists"}), 409
    # Sweep every market key, not the bare "assets_list" (which list_assets
    # never writes). The full sweep also covers a market change on this edit,
    # where BOTH the old and new market's cached lists are now stale.
    for mk in Asset.MARKETS + ["all"]:
        cache.delete(f"assets_list_{mk}")
    return jsonify(asset.to_dict()), 200


@assets_bp.route("/<int:asset_id>", methods=["DELETE"])
@super_admin_required
def delete_asset(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    # Soft delete — keeps historical signals intact
    asset.is_active = False
    db.session.commit()
    for mk in Asset.MARKETS + ["all"]:
        cache.delete(f"assets_list_{mk}")
    return jsonify({"message": f"{asset.symbol} removed from platform"}), 200


@assets_bp.route("/markets", methods=["GET"])
@login_required
def get_markets():
    """The canonical market registry (app.services.markets), for any page
    that wants to populate a market dropdown/filter without hardcoding its
    own <option> list — see that module's docstring for why this exists.
    Was returning just the bare key list with no live consumer; now
    includes labels too, both keyed and in registry order, since a
    dropdown needs the human label as much as the value. Public within the
    login-required surface (no admin gate) since this is just labels, not
    configuration."""
    from app.services.markets import MARKETS, MARKET_LABELS
    return jsonify({"markets": Asset.MARKETS, "labels": MARKET_LABELS, "registry": MARKETS}), 200


def _gather_asset_context(asset) -> dict:
    """Real, currently-true data about `asset` for the LLM to ground its
    answer in -- price/indicators/latest signal/news, each independently
    best-effort (a failure in one shouldn't blank out the others). Never
    fabricated; whatever's missing is just left out of the prompt, and
    answer_asset_question()'s own prompt tells the model to say so rather
    than invent a number for a gap here."""
    context: dict = {}

    try:
        ticker = market_fetcher.fetch_ticker(asset)
        if ticker:
            context["price"] = ticker.get("price")
            context["change_pct"] = ticker.get("change_pct")
    except Exception:
        pass

    try:
        df = market_fetcher.fetch(asset, "1h", 60)
        if df is not None and len(df) >= 20:
            from app.services.indicators.calculator import calculate_all_indicators
            ind = calculate_all_indicators(df, light=True)
            parts = []
            rsi = ind.get("rsi")
            if rsi is not None:
                parts.append(f"RSI {rsi:.0f}")
            ema9, ema21 = ind.get("ema9"), ind.get("ema21")
            if ema9 and ema21:
                parts.append("EMA9>EMA21 (short-term uptrend)" if ema9 > ema21 else "EMA9<EMA21 (short-term downtrend)")
            st_dir = ind.get("supertrend_direction")
            if st_dir:
                parts.append(f"Supertrend {st_dir}")
            adx = ind.get("adx")
            if adx is not None:
                parts.append(f"ADX {adx:.0f} ({'trending' if adx >= 20 else 'range-bound'})")
            if parts:
                context["indicators"] = ", ".join(parts) + " (1h timeframe)"
    except Exception:
        pass

    try:
        from app.models.signal import Signal
        sig = (Signal.query.filter_by(asset_id=asset.id)
               .order_by(Signal.generated_at.desc()).first())
        if sig:
            context["latest_signal"] = (
                f"{sig.signal_type} on {sig.timeframe} at {sig.entry_price}, "
                f"confidence {sig.confidence_score:.0f}%, status: {sig.status}, "
                f"generated {sig.generated_at.strftime('%Y-%m-%d %H:%M UTC')}"
            )
    except Exception:
        pass

    try:
        from app.models.news import News
        recent = News.query.order_by(News.published_at.desc()).limit(200).all()
        matched = [n.title for n in recent if n.related_assets and asset.symbol in n.related_assets][:3]
        if matched:
            context["news"] = "; ".join(matched)
    except Exception:
        pass

    return context


def _llm_qa_quota_ok() -> bool:
    """Coarse platform-wide cap on top of the per-user rate limit on the
    route below -- protects the shared free-tier LLM key (one admin-
    configured key used by every user) from being exhausted by many
    different users each individually staying under their own limit. An
    hourly bucket keyed by the current UTC hour, not a precise sliding
    window -- good enough as a hard ceiling, not billing-grade accounting."""
    from datetime import datetime
    key = f"llm_qa_quota_{datetime.utcnow().strftime('%Y%m%d%H')}"
    count = cache.get(key) or 0
    if count >= 100:
        return False
    cache.set(key, count + 1, timeout=3700)
    return True


def _gather_general_context() -> dict:
    """Platform-wide snapshot for the global Ask AI widget when it's opened
    on a page with no specific asset in view (Dashboard, Terminal,
    Settings, etc.) -- same "real data only, gaps left out" contract as
    _gather_asset_context(), just scoped to the whole platform instead of
    one symbol."""
    context: dict = {}

    try:
        from app.models.signal import Signal, SignalHistory
        context["active_signals"] = Signal.query.filter_by(status="active").count()
        total_h = SignalHistory.query.count()
        if total_h:
            wins = SignalHistory.query.filter(SignalHistory.outcome == "win").count()
            context["win_rate"] = round(wins / total_h * 100, 1)
            context["closed_trades_total"] = total_h
    except Exception:
        pass

    try:
        from app.models.signal import Signal as _Signal
        top = (_Signal.query.join(Asset, _Signal.asset_id == Asset.id)
               .filter(_Signal.signal_type.in_(["BUY", "SELL"]))
               .order_by(_Signal.generated_at.desc()).first())
        if top and top.asset:
            context["latest_signal"] = (
                f"{top.signal_type} on {top.asset.symbol} ({top.timeframe}), "
                f"confidence {top.confidence_score:.0f}%, status: {top.status}"
            )
    except Exception:
        pass

    return context


@assets_bp.route("/ask", methods=["POST"])
@premium_required
@subscription_feature_required("ai_enabled")
@limiter.limit("10 per hour")
def ask_ai_general():
    """Backs the global floating Ask AI widget (every page, not just asset
    detail) -- an optional `asset_id` grounds the answer in that asset's
    real data via the exact same _gather_asset_context()/
    answer_asset_question() path as ask_about_asset() below; omitted, it
    falls back to a platform-wide snapshot via _gather_general_context()/
    answer_general_question() so pages with no asset in view (Dashboard,
    Terminal, Settings) still get a grounded answer instead of a blank
    refusal. Shares the same tier gate, per-user rate limit and platform-
    wide hourly quota as the per-asset route since both draw on the same
    single free-tier LLM key."""
    data = request.get_json() or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400
    if len(question) > 300:
        return jsonify({"error": "question must be 300 characters or fewer"}), 400

    asset_id = data.get("asset_id")
    asset = Asset.query.get(asset_id) if asset_id else None

    from app.services.ai.llm_reasoning import is_configured, answer_asset_question, answer_general_question

    if not is_configured():
        return jsonify({
            "answer": None, "available": False,
            "message": "AI Q&A isn't set up yet — an admin needs to add a free LLM key under Admin > API Configurations.",
        }), 200

    if not _llm_qa_quota_ok():
        return jsonify({
            "answer": None, "available": True,
            "message": "AI Q&A has hit its shared hourly limit across all users — try again in a bit.",
        }), 200

    if asset:
        context = _gather_asset_context(asset)
        answer = answer_asset_question(asset.symbol, asset.market, question, context)
    else:
        context = _gather_general_context()
        answer = answer_general_question(question, context)

    if not answer:
        return jsonify({
            "answer": None, "available": True,
            "message": "Couldn't get an answer just now — try again shortly.",
        }), 200

    return jsonify({"answer": answer, "available": True}), 200


@assets_bp.route("/<int:asset_id>/ask", methods=["POST"])
@premium_required
@subscription_feature_required("ai_enabled")
@limiter.limit("10 per hour")
def ask_about_asset(asset_id):
    """Free-form Q&A about one asset, answered by the same admin-configured
    LLM that writes signal reasoning (app/services/ai/llm_reasoning.py) --
    grounded in _gather_asset_context()'s real data, never the model's own
    unguided knowledge. Gated the same way as AI Predictions (premium tier
    + ai_enabled feature flag) since this shares one free-tier API key
    across the whole platform and a fully open, unlimited chat surface
    would burn through that budget fast."""
    asset = Asset.query.get_or_404(asset_id)
    data = request.get_json() or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400
    if len(question) > 300:
        return jsonify({"error": "question must be 300 characters or fewer"}), 400

    from app.services.ai.llm_reasoning import is_configured, answer_asset_question

    if not is_configured():
        return jsonify({
            "answer": None, "available": False,
            "message": "AI Q&A isn't set up yet — an admin needs to add a free LLM key under Admin > API Configurations.",
        }), 200

    if not _llm_qa_quota_ok():
        return jsonify({
            "answer": None, "available": True,
            "message": "AI Q&A has hit its shared hourly limit across all users — try again in a bit.",
        }), 200

    context = _gather_asset_context(asset)
    answer = answer_asset_question(asset.symbol, asset.market, question, context)
    if not answer:
        return jsonify({
            "answer": None, "available": True,
            "message": "Couldn't get an answer just now — try again shortly.",
        }), 200

    return jsonify({"answer": answer, "available": True}), 200


@assets_bp.route("/search", methods=["GET"])
@admin_required
def search_asset():
    """
    Search for a symbol/name to add. Crypto results come from Delta Exchange
    India's live product list (shown first, tagged source="delta_exchange").
    Everything else is searched via Yahoo Finance (tagged source="yahoo").
    """
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"results": []}), 200

    results = []

    # ── Delta Exchange India — crypto perpetuals (shown first) ──────────
    try:
        results.extend(_search_delta_products(q))
    except Exception as e:
        pass  # Delta search is best-effort; Yahoo results still return below

    # ── Yahoo Finance — everything else ──────────────────────────────────
    try:
        import requests as _req
        url = "https://query1.finance.yahoo.com/v1/finance/search"
        params = {"q": q, "quotesCount": 15, "newsCount": 0, "enableFuzzyQuery": True, "enableNavLinks": False}
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = _req.get(url, params=params, headers=headers, timeout=8)
        resp.raise_for_status()
        quotes = resp.json().get("quotes", [])
        for item in quotes:
            sym  = item.get("symbol", "")
            name = item.get("longname") or item.get("shortname") or sym
            exch = item.get("exchange", "")
            typ  = item.get("quoteType", "")
            if sym:
                results.append({
                    "symbol": sym, "name": name, "exchange": exch, "type": typ,
                    "source": "yahoo", "market": None,
                })
    except Exception:
        pass

    return jsonify({"results": results}), 200


def _search_delta_products(q: str) -> list[dict]:
    """Search Delta Exchange India's live perpetual-futures product list by
    symbol or underlying-asset name. Cached for 5 minutes to avoid hammering
    the products endpoint on every keystroke."""
    import requests as _req

    products = cache.get("delta_products_all")
    if products is None:
        resp = _req.get(
            "https://api.india.delta.exchange/v2/products",
            params={"contract_types": "perpetual_futures"},
            timeout=8,
        )
        resp.raise_for_status()
        products = resp.json().get("result", [])
        cache.set("delta_products_all", products, timeout=300)

    q_upper = q.upper()
    matches = []
    for p in products:
        symbol   = p.get("symbol", "")
        underlying = p.get("underlying_asset", {}) or {}
        base_sym = underlying.get("symbol", "")
        base_name = underlying.get("name", "")
        # Only offer USD-quoted perpetuals (our symbol map / fetcher assumes *USD)
        if not symbol.endswith("USD") or p.get("state") != "live":
            continue
        if q_upper not in symbol.upper() and q_upper not in base_sym.upper() and q.lower() not in base_name.lower():
            continue
        # Present as our stored-symbol convention (e.g. BTCUSD -> BTCUSDT) so
        # it matches the DELTA_SYMBOL_MAP / DB symbol format used elsewhere.
        our_symbol = base_sym.upper() + "USDT" if base_sym else symbol
        matches.append({
            "symbol": our_symbol,
            "name": base_name or symbol,
            "exchange": "Delta Exchange India",
            "type": "CRYPTOCURRENCY",
            "source": "delta_exchange",
            "market": "crypto",
            "delta_symbol": symbol,
        })
        if len(matches) >= 15:
            break
    return matches


@assets_bp.route("/delta-catalog", methods=["GET"])
@admin_required
def delta_catalog():
    """Every live, USD-quoted Delta Exchange perpetual — the same universe
    _search_delta_products() matches against, but without a query filter,
    so the admin Assets page can render the whole catalog as toggle cards
    instead of the admin having to search and add symbols one at a time.
    Annotated with whether each symbol is already tracked (and active), so
    the frontend can render a single enable/disable toggle per card that
    reuses the existing add-from-search / PUT is_active endpoints.
    """
    import requests as _req

    products = cache.get("delta_products_all")
    if products is None:
        resp = _req.get(
            "https://api.india.delta.exchange/v2/products",
            params={"contract_types": "perpetual_futures"},
            timeout=8,
        )
        resp.raise_for_status()
        products = resp.json().get("result", [])
        cache.set("delta_products_all", products, timeout=300)

    existing = {a.symbol: a for a in Asset.query.filter_by(exchange="delta_exchange").all()}

    catalog = []
    seen = set()
    for p in products:
        symbol = p.get("symbol", "")
        underlying = p.get("underlying_asset", {}) or {}
        base_sym = underlying.get("symbol", "")
        base_name = underlying.get("name", "")
        if not symbol.endswith("USD") or p.get("state") != "live":
            continue
        our_symbol = base_sym.upper() + "USDT" if base_sym else symbol
        if our_symbol in seen:
            continue
        seen.add(our_symbol)
        a = existing.get(our_symbol)
        catalog.append({
            "symbol": our_symbol,
            "name": base_name or symbol,
            "tracked": a is not None,
            "asset_id": a.id if a else None,
            "is_active": bool(a.is_active) if a else False,
        })
    catalog.sort(key=lambda c: c["symbol"])
    return jsonify({"catalog": catalog, "total": len(catalog)}), 200


@assets_bp.route("/add-from-search", methods=["POST"])
@super_admin_required
def add_from_search():
    """Add an asset found via search to the platform. Delta-sourced results
    are always added as crypto, routed to Delta Exchange for data — never Yahoo."""
    data, error, status = _asset_body()
    if error:
        return error, status
    try:
        symbol = _asset_text(data, "symbol", required=True, uppercase=True)
        name = _asset_text(data, "name", required=True)
        exchange = _asset_text(data, "exchange") or ""
        source = _asset_text(data, "source") or "yahoo"
        market = _asset_text(data, "market") or "index"
        if source not in {"yahoo", "delta_exchange"}:
            raise ValueError("source must be yahoo or delta_exchange")
        if market not in Asset.MARKETS:
            raise ValueError(f"market must be one of {Asset.MARKETS}")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if source == "delta_exchange":
        from app.services.data.fetcher import to_delta_symbol
        if not to_delta_symbol(symbol):
            return jsonify({"error": f"{symbol} is not a valid Delta Exchange symbol"}), 400
        market      = "crypto"
        exchange    = "delta_exchange"
        data_source = "delta_exchange"
    else:
        data_source = "yahoo"

    existing = Asset.query.filter_by(symbol=symbol).first()
    if existing:
        if existing.is_active:
            return jsonify({"error": f"{symbol} already exists", "asset": existing.to_dict()}), 409
        # Previously soft-deleted — reactivate instead of blocking re-add
        existing.name        = name
        existing.market      = market
        existing.exchange    = exchange
        existing.data_source = data_source
        existing.is_active   = True
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": "An asset with this symbol and exchange already exists"}), 409
        for mk in Asset.MARKETS + ["all"]:
            cache.delete(f"assets_list_{mk}")
        return jsonify({"message": f"{symbol} re-added successfully", "asset": existing.to_dict()}), 201

    asset = Asset(
        symbol=symbol,
        name=name,
        market=market,
        exchange=exchange,
        data_source=data_source,
        is_active=True,
    )
    db.session.add(asset)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "An asset with this symbol and exchange already exists"}), 409
    # clear asset list cache for all markets
    for mk in Asset.MARKETS + ["all"]:
        cache.delete(f"assets_list_{mk}")
    return jsonify({"message": f"{symbol} added successfully", "asset": asset.to_dict()}), 201
