"""Serves the built Vite bundle, with every unmatched route falling back to ``index.html``.

Split out of :mod:`backend.api`, which is the read-only ``/api`` surface the web view consumes and
carries no static-file serving of its own.
"""

from __future__ import annotations

import logging
import pathlib

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

logger = logging.getLogger(__name__)

# --- Serving the built frontend --------------------------------------------


#: The paths FastAPI generates its schema and docs pages at. A deploy builds the app without them
#: (#1476), and they must then 404 rather than fall through to the bundle; a local run registers them
#: ahead of the fallback, so refusing them here never hides them there.
_FASTAPI_DOCS_PATHS = frozenset({"openapi.json", "docs", "docs/oauth2-redirect", "redoc"})


def mount_frontend(app: FastAPI, dist: pathlib.Path) -> None:
    """Serve the Vite bundle in *dist*, with every unmatched route falling back to ``index.html``.

    Call this **last**: the fallback matches everything, so any route registered after it is dead.

    A missing or incomplete build is not an error — local development and the test suite run without
    one. Nothing is mounted and the API still serves.
    """
    index = dist / "index.html"
    assets = dist / "assets"
    if not (index.is_file() and assets.is_dir()):
        logger.warning("No frontend build at %s: the web view is not served.", dist)
        return

    app.mount("/assets", StaticFiles(directory=assets), name="assets")

    service_worker = dist / "sw.js"
    if service_worker.is_file():

        @app.get("/sw.js", include_in_schema=False)
        def kill_switch() -> FileResponse:
            """The self-destructing worker in ``frontend/public/sw.js`` that evicts the pre-v4 PWA's.

            The media type is stated rather than guessed: a browser refuses to update a service worker
            from anything but JavaScript, and a refused update leaves the stale worker in charge.
            """
            return FileResponse(service_worker, media_type="text/javascript")

    @app.get("/{spa_path:path}", include_in_schema=False)
    def spa(spa_path: str) -> FileResponse:
        """Hand every route the bundle, so a reload on /things/<uuid> resolves client-side.

        A path whose last segment looks like a filename is not a route and gets a 404: the old
        ``site.webmanifest`` or a stale asset should fail loudly, not masquerade as HTML — and a service
        worker whose script URL 404s is the one thing a browser unregisters on its own.
        """
        if spa_path in _FASTAPI_DOCS_PATHS:
            raise HTTPException(status_code=404, detail=f"no route at /{spa_path}")
        if "." in spa_path.rsplit("/", 1)[-1]:
            raise HTTPException(status_code=404, detail=f"no file at /{spa_path}")
        return FileResponse(index)
