"""HTTP transport over the sleepmix core.

Everything in this package is a thin adapter: it decodes a request, calls into
``sleepmix.*``, and encodes the result. No audio processing lives here — that
keeps the CLI and the Python API first-class rather than degraded citizens of
the UI, and it keeps the core testable without starting a server.

FastAPI and uvicorn are an optional extra (``pip install "sleepmix[ui]"``) and
are imported only from inside this package.
"""
from __future__ import annotations
