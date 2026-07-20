"""Development entry point."""
import os
import sys

# Windows consoles default to cp1252, which cannot encode the ✓/✗/↷/✔ glyphs
# used in log messages — that raised UnicodeEncodeError *inside* logging and
# produced "--- Logging error ---" spam that buried the real error. Force UTF-8
# with errors="replace" (before importing the app, so logging handlers bind to
# the reconfigured streams) so no log line can crash on an unencodable char.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# joblib 1.5.3 (latest) still does `array.shape = self.shape` internally when
# unpickling models, which NumPy 2.5 deprecated — so every joblib.load() of a
# cached ML model prints a DeprecationWarning from joblib's OWN code that we
# can't act on. Filtered by exact message so genuine DeprecationWarnings from
# our code still surface. Remove once joblib ships a NumPy 2.5-compatible fix.
import warnings
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r".*Setting the shape on a NumPy array has been deprecated.*",
)

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
