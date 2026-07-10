"""Development entry point."""
import os
from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        # Derive from the already-resolved app config instead of
        # re-deriving from the raw FLASK_ENV env var — config.py defaults
        # FLASK_ENV to "development" when unset, but this comparison did
        # not, so leaving FLASK_ENV unset picked DevelopmentConfig
        # (DEBUG=True) while still passing debug=False here. socketio.run()
        # applies that debug flag back onto app.config["DEBUG"], silently
        # flipping it to False at runtime regardless of which config class
        # was actually loaded.
        debug=app.config.get("DEBUG", False),
        use_reloader=False,
        log_output=True,
        allow_unsafe_werkzeug=True,
    )
