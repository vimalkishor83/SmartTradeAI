"""Production WSGI entry point for Gunicorn."""
from app import create_app
from app.extensions import socketio

app = create_app()
application = app  # alias for compatibility
