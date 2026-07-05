"""Serve the alternate front-ends (frontend-New1, frontend-New2).

Additive and fully isolated: these routes serve two brand-new self-contained SPAs
from sibling folders, mounted at /new1 and /new2. They consume the existing
/api/v1/* REST APIs (same origin → JWT bearer works, no CORS needed). The original
`frontend/` and its Flask template/static config are untouched.
"""
import os

from flask import Blueprint, send_from_directory

frontends_bp = Blueprint("frontends", __name__)

# Project root (one level above this app/ package).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _serve(folder: str, path: str):
    directory = os.path.join(_ROOT, folder)
    rel = path or "index.html"
    full = os.path.join(directory, rel)
    # SPA fallback: unknown paths (client-side routes) serve index.html
    if not os.path.isfile(full):
        rel = "index.html"
    return send_from_directory(directory, rel)


@frontends_bp.route("/new1/", defaults={"path": ""})
@frontends_bp.route("/new1/<path:path>")
def new1(path):
    return _serve("frontend-New1", path)


@frontends_bp.route("/new2/", defaults={"path": ""})
@frontends_bp.route("/new2/<path:path>")
def new2(path):
    return _serve("frontend-New2", path)
