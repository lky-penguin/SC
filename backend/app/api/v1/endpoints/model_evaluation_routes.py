"""模型评价读取与流式生成。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.sse import sse_response
from app.api.utils import unwrap
from app.db import get_db
from app.schemas.model_evaluation import ModelEvaluationRequest
from app.services.model_evaluation_service import ModelEvaluationService

router = APIRouter(prefix="/model-versions", tags=["模型评价"])


@router.get("/{model_id}/evaluation")
def get_evaluation(model_id: int, db: Session = Depends(get_db)):
    return unwrap(ModelEvaluationService(db).get_evaluation(model_id))


@router.post("/{model_id}/evaluation/stream")
def stream_evaluation(model_id: int, payload: ModelEvaluationRequest, db: Session = Depends(get_db)):
    service = ModelEvaluationService(db)
    return sse_response(service.stream(model_id, payload.regenerate))
