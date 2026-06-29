from flask import Blueprint, render_template, redirect, url_for
from app.models.asset import Asset

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
def index():
    return redirect(url_for("views.dashboard"))


@views_bp.route("/home")
def landing():
    return render_template("landing.html")


@views_bp.route("/dashboard")
def dashboard():
    return render_template("dashboard/index.html")


@views_bp.route("/login")
def login():
    return render_template("auth/login.html")


@views_bp.route("/register")
def register():
    return render_template("auth/register.html")


@views_bp.route("/markets/<market>")
def markets(market):
    if market == "commodities":
        return render_template("markets/commodities.html", market="commodities")
    return render_template("markets/index.html", market=market)


@views_bp.route("/scanner")
def scanner():
    return render_template("dashboard/scanner.html")


@views_bp.route("/backtesting")
def backtesting():
    return render_template("dashboard/backtesting.html")


@views_bp.route("/portfolio")
def portfolio():
    return render_template("dashboard/portfolio.html")


@views_bp.route("/watchlist")
def watchlist():
    return render_template("dashboard/watchlist.html")


@views_bp.route("/signals")
def signals():
    return render_template("dashboard/signals.html")


@views_bp.route("/analytics")
def analytics():
    return render_template("dashboard/analytics.html")


@views_bp.route("/news")
def news():
    return render_template("dashboard/news.html")


@views_bp.route("/ai-insights")
def ai_insights():
    return render_template("dashboard/ai_insights.html")


@views_bp.route("/risk")
def risk():
    return render_template("dashboard/risk.html")


@views_bp.route("/settings")
def settings():
    return render_template("dashboard/settings.html")


@views_bp.route("/auto-generate")
def auto_generate():
    return render_template("dashboard/auto_generate.html")


@views_bp.route("/mtf-analysis")
def mtf_analysis():
    return render_template("dashboard/mtf_analysis.html")


@views_bp.route("/ta-summary")
def ta_summary():
    return render_template("dashboard/ta_summary.html")


@views_bp.route("/admin")
def admin():
    return render_template("admin/index.html")


@views_bp.route("/admin/users")
def admin_users():
    return render_template("admin/users.html")


@views_bp.route("/admin/logs")
def admin_logs():
    return render_template("admin/logs.html")


@views_bp.route("/asset/<int:asset_id>")
def asset_detail(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    return render_template("asset/detail.html", asset=asset, asset_id=asset_id)
