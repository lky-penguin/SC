"""模型版本的纯展示序列化。"""
from __future__ import annotations

from app.models.model_version import ModelVersion
from app.services.constants import dataset_display_name_of
from app.utils.serialization import row_to_dict


def model_version_to_dict(
    model: ModelVersion,
    *,
    include_model_attributes: bool = False,
) -> dict:
    dataset = model.dataset
    algorithm = model.algorithm
    data = row_to_dict(
        model,
        exclude=("model_attributes", "ai_evaluation", "training_parameters"),
    )

    from app.services.model_evaluation_service import (
        build_model_attributes,
        evaluation_is_current,
    )

    attributes = build_model_attributes(model)
    public_attributes = attributes if include_model_attributes else {
        "contract_version": attributes.get("contract_version"),
        "model_version_id": attributes.get("model_version_id"),
        "dataset": attributes.get("dataset"),
        "algorithm": attributes.get("algorithm"),
        "quality_metrics": attributes.get("quality_metrics") or {},
        "feature_profile": [],
        "evaluation_scope": attributes.get("evaluation_scope"),
    }

    data.update(
        {
            "model_version_id": model.id,
            "dataset_name": dataset_display_name_of(dataset),
            "dataset_version": dataset.version if dataset else None,
            "algorithm_code": algorithm.code if algorithm else None,
            "algorithm_name": algorithm.display_name if algorithm else None,
            "evaluation_metrics": dict(model.evaluation_metrics or {}),
            "training_parameters": model.training_parameters or {},
            "model_attributes": public_attributes,
            "model_evaluation_available": evaluation_is_current(
                (model.ai_evaluation or {}).get("current") or {},
                attributes,
            ),
        }
    )
    return data
