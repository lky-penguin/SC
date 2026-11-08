"""数据集的纯展示序列化，不访问数据库。"""
from __future__ import annotations

from pathlib import Path

from app.models.dataset import Dataset
from app.models.dataset_revision import DatasetRevision
from app.services.constants import DATASET_STATUS_ACTIVE, dataset_display_name_of
from app.services.dataset_iteration import change_type_label
from app.services.dataset_storage import dataset_format, normalize_dataset_path
from app.utils.serialization import row_to_dict


def dataset_to_dict(
    dataset: Dataset,
    *,
    record_count: int,
    referenced: bool,
) -> dict:
    """序列化数据集并补充前端列表/详情字段。"""
    data = row_to_dict(dataset)
    data.pop("logical_id", None)
    normalized = normalize_dataset_path(dataset.file_path)
    data.update(
        {
            "name": dataset_display_name_of(dataset),
            "field_count": len(dataset.fields_schema or []),
            "data_format": dataset_format(dataset.file_path),
            "file_name": Path(normalized).name,
            "record_count": record_count,
            "referenced": referenced,
            "enabled": dataset.status == DATASET_STATUS_ACTIVE,
            "change_type": dataset.change_type,
            "change_type_label": (
                change_type_label(dataset.change_type) if dataset.change_type else None
            ),
            "is_breaking": bool(dataset.is_breaking),
            "base_version_id": dataset.base_version_id,
        }
    )
    return data


def revision_to_dict(revision: DatasetRevision) -> dict:
    """序列化一条数据集迭代记录。"""
    return {
        "id": revision.id,
        "dataset_id": revision.dataset_id,
        "change_type": revision.change_type,
        "change_type_label": change_type_label(revision.change_type),
        "is_breaking": bool(revision.is_breaking),
        "mode": revision.mode,
        "result_dataset_id": revision.result_dataset_id,
        "reason": revision.reason,
        "summary": revision.summary,
        "detail": revision.detail,
        "created_at": (
            revision.created_at.isoformat() if revision.created_at else None
        ),
    }
