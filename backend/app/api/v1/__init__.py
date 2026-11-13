# v1路由入口，各模块统一挂载
from fastapi import APIRouter
from app.api.v1.endpoints import ai_setting_routes, algorithm_routes, dataset_routes, model_evaluation_routes, model_version_routes
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(dataset_routes.router)
api_router.include_router(algorithm_routes.router)
api_router.include_router(model_version_routes.router)
api_router.include_router(model_evaluation_routes.router)
api_router.include_router(ai_setting_routes.router)
