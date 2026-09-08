"""Run a strict walk-forward AI Insights report on the server."""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.asset import Asset
from app.models.backtest_sweep import BacktestSweep
from app.models.user import User
from app.services.backtesting.ai_insights import (
    AI_INSIGHTS_ENGINE_VERSION,
    AI_INSIGHTS_STRATEGY,
    run_ai_insights_backtest,
)
from app.services.backtesting.sweep import (
    SWEEP_CANDLE_LIMIT,
    SWEEP_COMMISSION,
    SWEEP_INITIAL_CAPITAL,
    SWEEP_SLIPPAGE,
    SWEEP_SPREAD,
    SWEEP_TIMEFRAMES,
    run_strategy_sweep,
)


def _args():
    parser = argparse.ArgumentParser(description="Run the SmartTrade AI Insights walk-forward sweep")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--username", default=None)
    parser.add_argument("--candle-limit", type=int, default=SWEEP_CANDLE_LIMIT)
    parser.add_argument("--retrain-every", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = _args()
    if args.candle_limit < 180 or args.candle_limit > 2000:
        raise SystemExit("--candle-limit must be between 180 and 2000")
    if args.retrain_every < 1 or args.retrain_every > 100:
        raise SystemExit("--retrain-every must be between 1 and 100")

    app = create_app()
    with app.app_context():
        user = User.query.filter_by(username=args.username).first() if args.username else User.query.get(args.user_id)
        if not user or not user.is_active or not user.role or user.role.name != "admin":
            raise SystemExit("An active admin user is required to own the saved report")

        assets = Asset.query.filter(
            Asset.is_active.is_(True),
            Asset.symbol.in_(["SOLUSDT", "XRPUSDT"]),
        ).all()
        missing = sorted({"SOLUSDT", "XRPUSDT"} - {asset.symbol for asset in assets})
        if missing:
            raise SystemExit(f"Active assets not found: {', '.join(missing)}")

        sweep = BacktestSweep(
            user_id=user.id,
            name="SOLUSDT + XRPUSDT AI Insights Walk-Forward",
            status="pending",
            assets=[asset.symbol for asset in assets],
            strategies=[AI_INSIGHTS_STRATEGY["key"]],
            timeframes=list(SWEEP_TIMEFRAMES),
            candle_limit=args.candle_limit,
            initial_capital=SWEEP_INITIAL_CAPITAL,
            commission=SWEEP_COMMISSION,
            slippage=SWEEP_SLIPPAGE,
            spread=SWEEP_SPREAD,
            total_cells=len(assets) * len(SWEEP_TIMEFRAMES),
            completed_cells=0,
            result_data={"cells": []},
            summary={},
            errors=[],
            engine_version=AI_INSIGHTS_ENGINE_VERSION,
        )
        db.session.add(sweep)
        db.session.commit()
        print(f"Created AI Insights sweep {sweep.id}: {sweep.total_cells} cells", flush=True)

        def runner(df, asset, timeframe, strategy):
            return run_ai_insights_backtest(
                df,
                asset,
                timeframe,
                sweep.initial_capital,
                sweep.commission,
                sweep.slippage,
                sweep.spread,
                retrain_every=args.retrain_every,
            )

        run_strategy_sweep(
            sweep,
            assets,
            candle_limit=args.candle_limit,
            strategies=[AI_INSIGHTS_STRATEGY],
            timeframes=SWEEP_TIMEFRAMES,
            result_runner=runner,
            engine_version=AI_INSIGHTS_ENGINE_VERSION,
        )
        print(
            f"AI Insights sweep {sweep.id} finished: {sweep.status}, "
            f"{sweep.completed_cells}/{sweep.total_cells} cells",
            flush=True,
        )
        print(f"Report URL: /backtesting/strategy-sweep?run={sweep.id}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
