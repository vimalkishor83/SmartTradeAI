from flask import Blueprint, render_template, redirect, url_for, request
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


@views_bp.route("/forgot-password")
def forgot_password():
    return render_template("auth/forgot_password.html")


@views_bp.route("/reset-password")
def reset_password():
    return render_template("auth/reset_password.html")


@views_bp.route("/verify-email")
def verify_email():
    return render_template("auth/verify_email.html")


@views_bp.route("/terms")
def terms():
    return render_template("legal/terms.html")


@views_bp.route("/privacy")
def privacy():
    return render_template("legal/privacy.html")


@views_bp.route("/markets/<market>")
def markets(market):
    # Normalize the plural URL slug to the canonical data slug so Commodities
    # uses the same Markets Overview (index.html) as every other market and its
    # tab / signal filter (market=commodity) line up.
    if market == "commodities":
        market = "commodity"
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
    tab = request.args.get('tab', 'live')
    return render_template("dashboard/signals.html", active_tab=tab)


@views_bp.route("/analytics")
def analytics():
    return render_template("dashboard/analytics.html")


@views_bp.route("/news")
def news():
    return render_template("dashboard/news.html")


@views_bp.route("/ai-insights")
def ai_insights():
    return render_template("dashboard/ai_insights.html")


@views_bp.route("/model-performance")
def model_performance():
    return render_template("dashboard/model_performance.html")


@views_bp.route("/heatmap")
def heatmap():
    return render_template("dashboard/heatmap.html")


@views_bp.route("/risk")
def risk():
    return render_template("dashboard/risk.html")


@views_bp.route("/settings")
def settings():
    return render_template("dashboard/settings.html")


@views_bp.route("/advanced-analysis")
def advanced_analysis():
    return render_template("dashboard/advanced_analysis.html")


@views_bp.route("/auto-generate")
def auto_generate():
    return render_template("dashboard/auto_generate.html")


@views_bp.route("/trading")
def trading():
    return render_template("dashboard/trading.html")


@views_bp.route("/broker-connections")
def broker_connections():
    return render_template("dashboard/broker_connections.html")


@views_bp.route("/briefing")
def briefing():
    return render_template("dashboard/briefing.html")


@views_bp.route("/economic-calendar")
def economic_calendar_page():
    return render_template("dashboard/economic_calendar.html")


@views_bp.route("/mtf-analysis")
def mtf_analysis():
    return render_template("dashboard/mtf_analysis.html")


@views_bp.route("/performance")
def performance():
    return render_template("dashboard/performance.html")


@views_bp.route("/ta-summary")
def ta_summary():
    return render_template("dashboard/ta_summary.html")


@views_bp.route("/journal")
def journal():
    return render_template("dashboard/journal.html")


@views_bp.route("/admin")
def admin():
    return render_template("admin/index.html")


@views_bp.route("/admin/users")
def admin_users():
    return render_template("admin/users.html")


@views_bp.route("/admin/logs")
def admin_logs():
    return render_template("admin/logs.html")


@views_bp.route("/admin/api-configs")
def admin_api_configs():
    return render_template("admin/api_configs.html")


@views_bp.route("/admin/assets")
def admin_assets():
    return render_template("admin/assets.html")


@views_bp.route("/asset/<int:asset_id>")
def asset_detail(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    return render_template("asset/detail.html", asset=asset, asset_id=asset_id)


@views_bp.route("/help")
def help_page():
    return render_template("dashboard/help.html", active="help")
