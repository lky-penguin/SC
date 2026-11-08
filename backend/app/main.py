"""软件 C 个人本地入口：真实 Java 贝叶斯训练与模型管理。"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.v1 import api_router
from app.config import APP_NAME, APP_SLUG, APP_VERSION
from app.paths import PROJECT_ROOT
from app.services.algorithm_config import NB_ALGORITHM_SERVICE_URL, PMWNB_SERVICE_URL

logger = logging.getLogger(__name__)
WEB_ROOT = PROJECT_ROOT / "frontend"
DIST_ROOT = WEB_ROOT / "dist"
SITE_ROOT = DIST_ROOT if (DIST_ROOT / "index.html").exists() else WEB_ROOT


class SPAStaticFiles(StaticFiles):
    def __init__(self, *, api_prefixes: tuple[str, ...] = ("/api/",), **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._api_prefixes = api_prefixes

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            if scope.get("path", "").startswith(self._api_prefixes):
                raise
            if "." in path.rsplit("/", 1)[-1]:
                raise
            return await super().get_response("index.html", scope)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.services.training_runner import start, stop
    start()
    try:
        yield
    finally:
        stop()


def _java_health() -> dict:
    result = {}
    for name, url in (("pmwnb", PMWNB_SERVICE_URL), ("nb", NB_ALGORITHM_SERVICE_URL)):
        try:
            response = requests.get(f"{url}/health", timeout=3)
            result[name] = {"ok": response.ok, "body": response.json() if response.ok else response.text[:200]}
        except Exception as exc:  # noqa: BLE001
            result[name] = {"ok": False, "error": str(exc)}
    return result


def create_app() -> FastAPI:
    app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:18202", "http://localhost:18202"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/api/health", tags=["运行状态"])
    def health():
        from sqlalchemy import text
        from app.db import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        java = _java_health()
        return {
            "status": "ok",
            "app": APP_SLUG,
            "name": APP_NAME,
            "version": APP_VERSION,
            "database": "postgresql",
            "java": java,
            "java_ready": all(item.get("ok") for item in java.values()),
            "port": int(os.getenv("PORT", "18201")),
        }

    if (SITE_ROOT / "index.html").exists():
        app.mount("/", SPAStaticFiles(directory=str(SITE_ROOT), html=True), name="web")
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "18201")))
