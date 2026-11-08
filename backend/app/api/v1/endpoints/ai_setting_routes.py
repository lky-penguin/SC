"""个人本地 AI 配置接口。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.utils import unwrap
from app.db import get_db
from app.schemas.ai_setting import AISettingUpdate
from app.services.ai_service import AISettingService

router = APIRouter(prefix="/settings/ai", tags=["AI 设置"])


@router.get("")
def get_ai_setting(db: Session = Depends(get_db)):
    return unwrap(AISettingService(db).get())


@router.put("")
def update_ai_setting(payload: AISettingUpdate, db: Session = Depends(get_db)):
    return unwrap(AISettingService(db).update(payload.model_dump()))


@router.post("/test")
def test_ai_setting(db: Session = Depends(get_db)):
    return unwrap(AISettingService(db).test_connection())
