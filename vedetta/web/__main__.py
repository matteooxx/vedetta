"""Serve the interface with waitress.

    python -m vedetta.web            # 0.0.0.0:5003 inside the container
"""
from __future__ import annotations

import os

from waitress import serve

from .app import create_app


def main() -> None:
    host = os.environ.get("VEDETTA_WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("VEDETTA_WEB_PORT", "5003"))
    serve(create_app(), host=host, port=port, threads=4, ident="vedetta")


if __name__ == "__main__":
    main()
