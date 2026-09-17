"""seed missing default market assets

This repairs partially seeded environments without changing existing asset
rows. It is intentionally idempotent because development databases may have
received only a subset of the original seed data.
"""

from alembic import op
import sqlalchemy as sa


revision = "m7a8b9c0d1e2"
down_revision = "l4e5f6g7h8i9"
branch_labels = None
depends_on = None


_DEFAULT_ASSETS = [
    ("BTCUSDT", "Bitcoin", "crypto", "delta_exchange", "delta_exchange"),
    ("ETHUSDT", "Ethereum", "crypto", "delta_exchange", "delta_exchange"),
    ("BNBUSDT", "BNB", "crypto", "delta_exchange", "delta_exchange"),
    ("SOLUSDT", "Solana", "crypto", "delta_exchange", "delta_exchange"),
    ("XRPUSDT", "XRP", "crypto", "delta_exchange", "delta_exchange"),
    ("EURUSD", "Euro/USD", "forex", "forex", "yahoo"),
    ("GBPUSD", "GBP/USD", "forex", "forex", "yahoo"),
    ("USDJPY", "USD/JPY", "forex", "forex", "yahoo"),
    ("AUDUSD", "AUD/USD", "forex", "forex", "yahoo"),
    ("USDINR", "USD/INR", "forex", "forex", "yahoo"),
    ("XAUUSD", "Gold", "commodity", "commodity", "yahoo"),
    ("XAGUSD", "Silver", "commodity", "commodity", "yahoo"),
    ("CLUSD", "Crude Oil", "commodity", "commodity", "yahoo"),
    ("RELIANCE", "Reliance Industries", "indian_stock", "NSE", "yahoo"),
    ("TCS", "Tata Consultancy Services", "indian_stock", "NSE", "yahoo"),
    ("INFY", "Infosys", "indian_stock", "NSE", "yahoo"),
    ("HDFCBANK", "HDFC Bank", "indian_stock", "NSE", "yahoo"),
    ("ICICIBANK", "ICICI Bank", "indian_stock", "NSE", "yahoo"),
    ("SBIN", "State Bank of India", "indian_stock", "NSE", "yahoo"),
    ("NIFTY50", "Nifty 50", "index", "NSE", "yahoo"),
    ("BANKNIFTY", "Bank Nifty", "index", "NSE", "yahoo"),
    ("SENSEX", "BSE Sensex", "index", "BSE", "yahoo"),
    ("FINNIFTY", "Fin Nifty", "index", "NSE", "yahoo"),
    ("MIDCPNIFTY", "Midcap Nifty", "index", "NSE", "yahoo"),
]


def upgrade():
    bind = op.get_bind()
    assets = sa.table(
        "assets",
        sa.column("symbol", sa.String(length=30)),
        sa.column("name", sa.String(length=100)),
        sa.column("market", sa.String(length=30)),
        sa.column("exchange", sa.String(length=50)),
        sa.column("data_source", sa.String(length=50)),
        sa.column("is_active", sa.Boolean()),
    )

    for symbol, name, market, exchange, data_source in _DEFAULT_ASSETS:
        exists = bind.execute(
            sa.select(assets.c.symbol).where(
                sa.and_(
                    assets.c.symbol == symbol,
                    assets.c.exchange == exchange,
                )
            )
        ).first()
        if exists is None:
            bind.execute(
                sa.insert(assets).values(
                    symbol=symbol,
                    name=name,
                    market=market,
                    exchange=exchange,
                    data_source=data_source,
                    is_active=True,
                )
            )


def downgrade():
    # Do not delete asset rows on downgrade: some may have been edited or used
    # after this repair. A schema rollback must not destroy application data.
    pass
