"""数据集请求模型。"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DatasetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    file_path: str = Field(..., min_length=1, max_length=255)
    fields_schema: List[Dict[str, Any]] = Field(..., min_length=1)
    label_field: Optional[str] = Field(None, min_length=1, max_length=64)


class DatasetUpdate(BaseModel):
    file_path: Optional[str] = Field(None, max_length=255)
    fields_schema: Optional[List[Dict[str, Any]]] = None
    label_field: Optional[str] = Field(None, max_length=64)


class DatasetRevisionRequest(BaseModel):
    change_type: str = Field(..., min_length=1, max_length=24)
    file_path: Optional[str] = Field(None, max_length=255)
    fields_schema: Optional[List[Dict[str, Any]]] = None
    label_field: Optional[str] = Field(None, max_length=64)
    name: Optional[str] = Field(None, max_length=128)
    summary: Optional[str] = Field(None, max_length=255)


class DatasetAnalysisRequest(BaseModel):
    regenerate: bool = False
