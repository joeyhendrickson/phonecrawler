"""ASGI entrypoint for Vercel and `uvicorn server:app`."""

from app.web.server import app

__all__ = ["app"]
