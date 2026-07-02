from flask import Blueprint, request, jsonify
from app.models.asset import Asset
from app.extensions import db, cache, limiter
from app.auth.decorators import login_required, admin_required
from app.services.data.fetcher import market_fetcher

assets_bp = Blueprint("assets", __name__)


@assets_bp.route("/", methods=["GET"])
@login_required
def list_assets():
    market = request.args.get("market")
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


@assets_bp.route("/", methods=["POST"])
@admin_required
def create_asset():
    data = request.get_json()
    required = ["symbol", "name", "market"]
    if not all(k in data for k in required):
        return jsonify({"error": "Missing required fields"}), 400
    asset = Asset(**{k: data[k] for k in data if hasattr(Asset, k)})
    db.session.add(asset)
    db.session.commit()
    cache.delete("assets_list")
    return jsonify(asset.to_dict()), 201


@assets_bp.route("/<int:asset_id>", methods=["PUT"])
@admin_required
def update_asset(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    data = request.get_json()
    for k, v in data.items():
        if hasattr(asset, k):
            setattr(asset, k, v)
    db.session.commit()
    cache.delete("assets_list")
    return jsonify(asset.to_dict()), 200


@assets_bp.route("/<int:asset_id>", methods=["DELETE"])
@admin_required
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
    return jsonify({"markets": Asset.MARKETS}), 200


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


@assets_bp.route("/add-from-search", methods=["POST"])
@admin_required
def add_from_search():
    """Add an asset found via search to the platform. Delta-sourced results
    are always added as crypto, routed to Delta Exchange for data — never Yahoo."""
    data = request.get_json() or {}
    symbol   = (data.get("symbol") or "").strip().upper()
    name     = (data.get("name") or "").strip()
    exchange = (data.get("exchange") or "").strip()
    source   = (data.get("source") or "yahoo").strip()
    market   = (data.get("market") or "index").strip()

    if not symbol or not name:
        return jsonify({"error": "symbol and name are required"}), 400

    existing = Asset.query.filter_by(symbol=symbol).first()
    if existing:
        return jsonify({"error": f"{symbol} already exists", "asset": existing.to_dict()}), 409

    if source == "delta_exchange":
        from app.services.data.fetcher import to_delta_symbol
        if not to_delta_symbol(symbol):
            return jsonify({"error": f"{symbol} is not a valid Delta Exchange symbol"}), 400
        market      = "crypto"
        exchange    = "delta_exchange"
        data_source = "delta_exchange"
    else:
        data_source = "yahoo"

    asset = Asset(
        symbol=symbol,
        name=name,
        market=market,
        exchange=exchange,
        data_source=data_source,
        is_active=True,
    )
    db.session.add(asset)
    db.session.commit()
    # clear asset list cache for all markets
    for mk in Asset.MARKETS + ["all"]:
        cache.delete(f"assets_list_{mk}")
    return jsonify({"message": f"{symbol} added successfully", "asset": asset.to_dict()}), 201
