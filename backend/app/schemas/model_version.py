"""模型训练请求模型。"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ModelVersionCreate(BaseModel):
    dataset_id: int = Field(..., gt=0)
    algorithm_id: int = Field(..., gt=0)
    training_parameters: Dict[str, Any] = Field(default_factory=dict)


class ModelVersionCompare(BaseModel):
    model_ids: List[int] = Field(..., min_length=1)


class ModelVersionExportBatch(BaseModel):
    model_ids: List[int] = Field(..., min_length=1, max_length=200)


class ModelVersionCompleteTraining(BaseModel):
    evaluation_metrics: Dict[str, Any]


class ModelVersionFailTraining(BaseModel):
    error_message: Optional[str] = None
