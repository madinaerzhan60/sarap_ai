"""Vercel ASGI entrypoint for the SARAP FastAPI application."""

from pathlib import Path
import sys


backend = Path(__file__).resolve().parents[1] / "backend"
if str(backend) not in sys.path:
    sys.path.insert(0, str(backend))

from app.main import app  # noqa: E402,F401
