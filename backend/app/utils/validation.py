"""请求参数、字段结构与训练参数校验。"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def validate_required(data: dict[str, Any], fields: Sequence[str]) -> str | None:
    """校验必填字段：缺失、None 或空字符串均视为非法。"""
    for field in fields:
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            return f"缺少必填字段: {field}"
    return None


def validate_length(
    value: str, field_name: str, max_len: int, min_len: int = 1
) -> str | None:
    """按字符数校验字符串长度。"""
    length = len(value or "")
    if length < min_len or length > max_len:
        return f"{field_name} 长度必须在 [{min_len}, {max_len}] 之间"
    return None


def validate_fields_schema(fields_schema: Any, label_field: str) -> str | None:
    """校验数据集字段结构。"""
    if not isinstance(fields_schema, list) or not fields_schema:
        return "fields_schema 必须是非空字段列表"
    feature_count = 0
    label_found = False
    seen_names: set[str] = set()
    for index, field in enumerate(fields_schema):
        if not isinstance(field, dict) or not field.get("name"):
            return f"fields_schema 第 {index + 1} 项缺少 name"
        if field["name"] in seen_names:
            return f"fields_schema 字段重名: {field['name']}，禁止训练（需求 3.1.1）"
        seen_names.add(field["name"])
        role = field.get("role")
        if role == "feature":
            feature_count += 1
        elif role == "label":
            if field["name"] == label_field:
                label_found = True
        else:
            return f"字段 {field.get('name')} 的 role 必须为 feature 或 label"
        if field.get("type") == "enum" and not field.get("enum_values"):
            return f"枚举字段 {field.get('name')} 缺少 enum_values 值域定义"
    if not feature_count:
        return "fields_schema 至少需要一个输入特征（role=feature）字段"
    if not label_found:
        return f"label_field '{label_field}' 必须在 fields_schema 中且 role=label"
    return None


def validate_params_schema(
    param_schema: Any, params: Any, dataset_has_numeric: bool = True
) -> str | None:
    """按算法注册的 param_schema 校验训练参数。"""
    if not isinstance(params, dict):
        return "training_parameters 必须是 JSON 对象"
    schema = param_schema or []
    if not isinstance(schema, list):
        return "param_schema 配置非法（必须是列表）"
    for item in schema:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        if item.get("requires_numeric_features") and not dataset_has_numeric:
            continue
        name = item["name"]
        required = bool(item.get("required", False))
        if name not in params:
            if required:
                return f"缺少必填训练参数: {name}"
            continue
        value = params[name]
        param_type = str(item.get("type", "")).lower()
        if param_type == "enum":
            allowed = item.get("enum_values") or []
            if str(value) not in {str(candidate) for candidate in allowed}:
                return f"训练参数 {name} 取值 {value} 不在枚举值域内: {allowed}"
        elif param_type in ("int", "integer", "float", "number"):
            try:
                numeric = float(value) if param_type in ("float", "number") else int(value)
            except (TypeError, ValueError):
                kind = "数值" if param_type in ("float", "number") else "整数"
                return f"训练参数 {name} 必须是{kind}"
            lower, upper = item.get("min"), item.get("max")
            if lower is not None and numeric < lower:
                return f"训练参数 {name} 不能小于 {lower}"
            if upper is not None and numeric > upper:
                return f"训练参数 {name} 不能大于 {upper}"
        elif param_type == "bool" and not isinstance(value, bool):
            return f"训练参数 {name} 必须是布尔值"
    return None


NUMERIC_FIELD_TYPES = frozenset(
    {"numeric", "real", "float", "double", "int", "integer", "number"}
)


def dataset_has_numeric_features(fields_schema: Any) -> bool:
    """判断数据集是否包含数值型输入特征。"""
    for field in fields_schema or []:
        if not isinstance(field, dict) or field.get("role") != "feature":
            continue
        if str(field.get("type", "")).lower() in NUMERIC_FIELD_TYPES:
            return True
    return False


def strip_inapplicable_params(
    param_schema: Any, params: Any, dataset_has_numeric: bool
) -> Any:
    """剔除对当前数据集无效的训练参数。"""
    if not isinstance(params, dict) or dataset_has_numeric:
        return params
    inapplicable = {
        item.get("name")
        for item in (param_schema or [])
        if isinstance(item, dict) and item.get("requires_numeric_features")
    }
    if not inapplicable:
        return params
    return {key: value for key, value in params.items() if key not in inapplicable}
