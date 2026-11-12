from __future__ import annotations
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope
from app.api.v1 import api_router
from app.config import API_PORT, APP_NAME, APP_SLUG, APP_VERSION, FRONTEND_PORT
from app.db import engine
from app.paths import PROJECT_ROOT
from app.services import training_runner
from app.services.algorithm_config import NB_ALGORITHM_SERVICE_URL, PMWNB_SERVICE_URL
logger = logging.getLogger(__name__)
JAVA_SERVICES = {
    "pmwnb": PMWNB_SERVICE_URL,
    "nb": NB_ALGORITHM_SERVICE_URL,
}
class SPAStaticFiles(StaticFiles):
    _api_prefixes = ("/api/",)
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            if scope.get("path", "").startswith(self._api_prefixes):  # API保持404，防止回退到SPA
                raise
            if "." in path.rsplit("/", 1)[-1]:  # 资源缺失时保持404，防止坏资源变成页面
                raise
            return await super().get_response("index.html", scope)
@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    training_runner.start()  # 训练队列跟随Web进程
    try:
        yield
    finally:
        training_runner.stop()
def create_app() -> FastAPI:
    app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://127.0.0.1:{FRONTEND_PORT}",
            f"http://localhost:{FRONTEND_PORT}",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    @app.get("/api/health", tags=["运行状态"])
    def health() -> dict[str, object]:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        java: dict[str, bool] = {}
        for name, url in JAVA_SERVICES.items():
            try:
                with requests.get(f"{url}/health", timeout=1.0) as response:
                    java[name] = response.ok
                    if not response.ok:
                        logger.warning("Java服务%s健康检查返回HTTP %s", name, response.status_code)
            except requests.RequestException as exc:
                logger.warning("Java服务%s健康检查失败: %s", name, exc)
                java[name] = False
        return {
            "status": "ok",
            "app": APP_SLUG,
            "name": APP_NAME,
            "version": APP_VERSION,
            "database": engine.dialect.name,
            "java": java,
            "java_ready": all(java.values()),
            "port": API_PORT,
        }
    web_root = PROJECT_ROOT / "frontend"
    dist_root = web_root / "dist"
    site_root = dist_root if (dist_root / "index.html").is_file() else web_root  # 先使用构建产物，未构建时回到源码目录
    if (site_root / "index.html").is_file():
        app.mount("/", SPAStaticFiles(directory=str(site_root), html=True), name="web")
    return app
app = create_app()
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=API_PORT)
