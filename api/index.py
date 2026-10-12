"""Vercel entrypoint: exposes the FastAPI ASGI app. All /api/* routes are rewritten here."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.app import create_app  # noqa: E402

app = create_app()
