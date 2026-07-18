"""
Production entry point — for running behind a reverse proxy (IIS + ARR +
URL Rewrite, see deploy/README.md), not for local development (use run.py
for that).

Binds to 127.0.0.1 only: this process is never meant to be reached directly
from outside the machine — IIS is the sole public-facing listener and
forwards everything to this port.
"""
import logging
import os

from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.getLogger(__name__).info(
        f"Starting SmartTradeAI (FLASK_ENV={os.environ.get('FLASK_ENV', 'development')}) "
        f"on 127.0.0.1:{port} — expects a reverse proxy in front of it."
    )
    socketio.run(
        app,
        host="127.0.0.1",
        port=port,
        debug=False,
        use_reloader=False,
        log_output=True,
        allow_unsafe_werkzeug=True,
    )
