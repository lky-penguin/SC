"""数据集上传、预览、迭代与算法适配接口；个人本地版无鉴权。"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.sse import sse_response
from app.api.utils import unwrap
from app.db import get_db
from app.schemas.common import ResponseModel
from app.schemas.dataset import DatasetAnalysisRequest, DatasetCreate, DatasetRevisionRequest, DatasetUpdate
from app.services.dataset_analysis_service import DatasetAnalysisService
from app.services.dataset_service import DatasetService

router = APIRouter(prefix="/datasets", tags=["数据集"])



@router.get("", response_model=ResponseModel)
def list_datasets(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=200), db: Session = Depends(get_db)):
    return unwrap(DatasetService(db).get_list(page=page, page_size=page_size))


@router.get("/{dataset_id}", response_model=ResponseModel)
def get_dataset(dataset_id: int, db: Session = Depends(get_db)):
    return unwrap(DatasetService(db).get(dataset_id))


@router.get("/{dataset_id}/versions", response_model=ResponseModel)
def get_dataset_versions(dataset_id: int, db: Session = Depends(get_db)):
    return unwrap(DatasetService(db).get_versions(dataset_id))


@router.get("/{dataset_id}/fields-schema", response_model=ResponseModel)
def get_fields(dataset_id: int, db: Session = Depends(get_db)):
    return unwrap(DatasetService(db).get_fields_schema(dataset_id))


@router.get("/{dataset_id}/preview", response_model=ResponseModel)
def preview(dataset_id: int, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=50), db: Session = Depends(get_db)):
    return unwrap(DatasetService(db).get_preview(dataset_id, page=page, page_size=page_size))


@router.post("", response_model=ResponseModel)
def create_dataset(payload: DatasetCreate, db: Session = Depends(get_db)):
    return unwrap(DatasetService(db).create(
        name=payload.name, file_path=payload.file_path,
        fields_schema=payload.fields_schema, label_field=payload.label_field,
    ))


@router.post("/upload", response_model=ResponseModel)
async def upload_dataset(
    file: UploadFile = File(...),
    name: str = Form(..., min_length=1, max_length=128),
    db: Session = Depends(get_db),
):
    data = await file.read()
    return unwrap(DatasetService(db).upload_from_file(
        name=name, filename=file.filename or "dataset.arff", file_bytes=data,
    ))


@router.put("/{dataset_id}", response_model=ResponseModel)
def update_dataset(dataset_id: int, payload: DatasetUpdate, db: Session = Depends(get_db)):
    return unwrap(DatasetService(db).update(dataset_id, **payload.model_dump(exclude_unset=True)))


@router.post("/{dataset_id}/revisions", response_model=ResponseModel)
def revise_dataset(dataset_id: int, payload: DatasetRevisionRequest, db: Session = Depends(get_db)):
    return unwrap(DatasetService(db).revise(dataset_id, **payload.model_dump(exclude_unset=True)))


@router.post("/{dataset_id}/revisions/append", response_model=ResponseModel)
async def append_rows(dataset_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read()
    return unwrap(DatasetService(db).append_rows(dataset_id, file.filename or "increment.arff", data))


@router.get("/{dataset_id}/revisions", response_model=ResponseModel)
def revisions(dataset_id: int, db: Session = Depends(get_db)):
    return unwrap(DatasetService(db).get_revisions(dataset_id))


@router.post("/{dataset_id}/disable", response_model=ResponseModel)
def disable_dataset(dataset_id: int, db: Session = Depends(get_db)):
    return unwrap(DatasetService(db).disable(dataset_id))


@router.get("/{dataset_id}/ai-analysis", response_model=ResponseModel)
def get_ai_analysis(dataset_id: int, db: Session = Depends(get_db)):
    return unwrap(DatasetAnalysisService(db).get_analysis(dataset_id))


@router.post("/{dataset_id}/ai-analysis/stream")
def stream_ai_analysis(dataset_id: int, payload: Optional[DatasetAnalysisRequest] = None, db: Session = Depends(get_db)):
    regenerate = bool(payload.regenerate) if payload else False
    return sse_response(DatasetAnalysisService(db).stream(dataset_id, regenerate))


@router.delete("/{dataset_id}", response_model=ResponseModel)
def delete_dataset(dataset_id: int, db: Session = Depends(get_db)):
    return unwrap(DatasetService(db).delete(dataset_id))
