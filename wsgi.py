"""Production WSGI entry point for Gunicorn (gunicorn --worker-class eventlet)."""
# eventlet.monkey_patch() must run before anything else imports socket/
# threading/ssl (Flask, SQLAlchemy, requests, etc.) — patching after those
# modules have already grabbed references to the unpatched stdlib is a
# classic source of subtle production-only hangs (greenlets blocking on a
# native socket, DB connections stalling under load) that don't reproduce
# in local dev (which runs the Werkzeug dev server via run.py, not
# gunicorn+eventlet, and never needed patching). Explicit and first-thing
# here rather than relying on gunicorn's eventlet worker class to patch
# for us, since that timing isn't guaranteed across gunicorn versions.
import eventlet
eventlet.monkey_patch()

import os  # noqa: E402

# Match Socket.IO's async mode to the worker class actually serving this
# module (gunicorn --worker-class eventlet, see Dockerfile). Set before
# create_app() so Config picks it up. Previously async_mode was hardcoded to
# "threading" in _init_extensions regardless of how the app was served, so the
# eventlet monkey-patch above bought nothing for the WebSocket transport.
os.environ.setdefault("SOCKETIO_ASYNC_MODE", "eventlet")

from app import create_app  # noqa: E402
from app.extensions import socketio  # noqa: E402

app = create_app()
application = app  # alias for compatibility
