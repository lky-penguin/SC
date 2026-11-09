"""模型训练、评估与模型文件导出接口。"""
from datetime import datetime, timezone
import io
from pathlib import Path
import zipfile

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.utils import unwrap
from app.db import get_db
from app.schemas.common import ResponseModel
from app.schemas.model_version import ModelVersionCreate, ModelVersionExportBatch
from app.services.model_package_service import ModelPackageService
from app.services.model_version_service import ModelVersionService

router = APIRouter(prefix="/model-versions", tags=["模型训练"])


@router.get("", response_model=ResponseModel)
def list_models(dataset_id: int | None = Query(None), page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=200), db: Session = Depends(get_db)):
    return unwrap(ModelVersionService(db).get_list(dataset_id=dataset_id, page=page, page_size=page_size))


@router.post("/train", response_model=ResponseModel)
def train_model(payload: ModelVersionCreate, db: Session = Depends(get_db)):
    return unwrap(ModelVersionService(db).train_and_save(payload.dataset_id, payload.algorithm_id, payload.training_parameters))


@router.post("/train-async", response_model=ResponseModel)
def train_model_async(payload: ModelVersionCreate, db: Session = Depends(get_db)):
    return unwrap(ModelVersionService(db).train_and_save_async(payload.dataset_id, payload.algorithm_id, payload.training_parameters))


@router.post("/packages/export")
def export_model_packages(payload: ModelVersionExportBatch, db: Session = Depends(get_db)):
    service = ModelPackageService(db)
    archive = io.BytesIO()
    model_ids = list(dict.fromkeys(payload.model_ids))
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as archive_file:
        for model_id in model_ids:
            export_result = service.export(model_id)
            if export_result.code != 0:
                status = export_result.code if 400 <= export_result.code <= 599 else 400
                return JSONResponse(status_code=status, content=export_result.model_dump())
            package_path = service.download(model_id)
            if not isinstance(package_path, Path):
                status = package_path.code if 400 <= package_path.code <= 599 else 400
                return JSONResponse(status_code=status, content=package_path.model_dump())
            archive_file.write(package_path, arcname=package_path.name)
    archive.seek(0)
    filename = f"model_packages_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Exported-Model-Count": str(len(model_ids)),
        },
    )


@router.get("/{model_id}", response_model=ResponseModel)
def get_model(model_id: int, db: Session = Depends(get_db)):
    return unwrap(ModelVersionService(db).get(model_id))


@router.post("/{model_id}/package", response_model=ResponseModel)
def export_model_package(model_id: int, db: Session = Depends(get_db)):
    return unwrap(ModelPackageService(db).export(model_id))


@router.get("/{model_id}/package")
def download_model_package(model_id: int, db: Session = Depends(get_db)):
    result = ModelPackageService(db).download(model_id)
    if not isinstance(result, Path):
        return unwrap(result)
    return FileResponse(
        path=str(result),
        media_type="application/zip",
        filename=result.name,
    )


@router.delete("/{model_id}", response_model=ResponseModel)
def delete_model(model_id: int, db: Session = Depends(get_db)):
    return unwrap(ModelVersionService(db).delete(model_id))
