"""算法注册信息只读接口。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.utils import unwrap
from app.db import get_db
from app.schemas.common import ResponseModel
from app.services.algorithm_service import AlgorithmService

router = APIRouter(prefix="/algorithms", tags=["算法"])


@router.get("", response_model=ResponseModel)
def list_algorithms(only_available: bool = Query(True), db: Session = Depends(get_db)):
    return unwrap(AlgorithmService(db).get_list(only_available=only_available))


@router.get("/{algorithm_id}", response_model=ResponseModel)
def get_algorithm(algorithm_id: int, db: Session = Depends(get_db)):
    return unwrap(AlgorithmService(db).get(algorithm_id))
