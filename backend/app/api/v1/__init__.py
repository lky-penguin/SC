"""软件 C API：只挂载数据集、算法、训练/模型、评价和设置。"""
from fastapi import APIRouter
from app.api.v1.endpoints import ai_setting_routes, algorithm_routes, dataset_routes, model_evaluation_routes, model_version_routes

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(dataset_routes.router)
api_router.include_router(algorithm_routes.router)
api_router.include_router(model_version_routes.router)
api_router.include_router(model_evaluation_routes.router)
api_router.include_router(ai_setting_routes.router)
