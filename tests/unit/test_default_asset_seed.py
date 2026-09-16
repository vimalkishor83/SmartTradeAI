from app import _seed_initial_data
from app.extensions import db
from app.models.asset import Asset


def test_seed_repairs_database_that_already_contains_one_asset(app):
    with app.app_context():
        db.session.query(Asset).delete()
        db.session.add(
            Asset(
                symbol="CLUSD",
                name="Crude Oil",
                market="commodity",
                exchange="commodity",
                data_source="yahoo",
            )
        )
        db.session.commit()

        _seed_initial_data(app)
        db.session.commit()

        symbols = {asset.symbol for asset in Asset.query.all()}
        assert {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD", "NIFTY50"}.issubset(symbols)
        assert len(symbols) == 24
