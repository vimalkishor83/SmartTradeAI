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
        debug=os.environ.get("FLASK_ENV") == "development",
        use_reloader=False,
        log_output=True,
        allow_unsafe_werkzeug=True,
    )
