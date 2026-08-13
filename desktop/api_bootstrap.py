"""Packaged FastAPI entry point for the macOS desktop application."""

from __future__ import annotations

import os

import uvicorn

from app.main import app


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("PERLER_HOST", "127.0.0.1"),
        port=int(os.environ.get("PERLER_PORT", "18080")),
        log_level="warning",
    )
