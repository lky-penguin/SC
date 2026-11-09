"""模型训练请求模型。"""
from typing import Any, Dict, List
from pydantic import BaseModel, Field


class ModelVersionCreate(BaseModel):
    dataset_id: int = Field(..., gt=0)
    algorithm_id: int = Field(..., gt=0)
    training_parameters: Dict[str, Any] = Field(default_factory=dict)


class ModelVersionExportBatch(BaseModel):
    model_ids: List[int] = Field(..., min_length=1, max_length=200)
