"""Dataset-to-contract adapters used by model export."""
from __future__ import annotations

import re
from typing import Any

from app.models.dataset import Dataset
from app.services.closed_loop_contract import fail
from app.services.constants import DATASET_POSITIVE_LABELS
from app.services.dataset_storage import resolve_dataset_path
from app.utils.arff_writer import arff_token
from app.utils.dataset_file_reader import read_all_rows

_RELATION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")


def data_class_for_dataset(dataset: Dataset) -> str:
    logical = (dataset.logical_id or "").upper()
    path = (dataset.file_path or "").upper()
    if logical.startswith("TEST_FIXTURE_") or logical.startswith("SAMPLE_") or "TEST_FIXTURE_" in path:
        return "test_fixture"
    if logical.startswith("DEMO_") or logical.startswith("DEMO-"):
        return "demo"
    return "production"


def display_label_for_dataset(dataset: Dataset, data_class: str) -> str:
    name = dataset.name or dataset.logical_id
    if data_class == "test_fixture":
        return f"TEST FIXTURE - {name} - NOT PRODUCTION"[:80]
    if data_class == "demo":
        return f"DEMO - {name} - NOT PRODUCTION"[:80]
    return name[:80]


def contract_fields(dataset: Dataset) -> tuple[list[dict[str, Any]], str, str]:
    schema = dataset.fields_schema or []
    if len(schema) < 2:
        fail("CL_SCHEMA_INCOMPATIBLE", "dataset schema must contain at least two fields")
    fields: list[dict[str, Any]] = []
    label_count = 0
    for source in schema:
        name = str(source.get("name", ""))
        if not name or re.search(r"[\s,{}@]", name) or len(name) > 128:
            fail("CL_SCHEMA_INCOMPATIBLE", f"field name is not contract-safe: {name!r}")
        ctype = str(source.get("type", "")).lower()
        role = source.get("role") if source.get("role") in {"feature", "label", "metadata", "identifier"} else "feature"
        item: dict[str, Any] = {"name": name, "role": role}
        if ctype == "enum":
            values = [str(value) for value in (source.get("enum_values") or [])]
            if not values:
                fail("CL_SCHEMA_INCOMPATIBLE", f"nominal field {name} has no domain")
            item.update({"wire_type": "nominal", "arff_type": "nominal", "arff_values": values})
        elif ctype == "numeric":
            item.update({"wire_type": "number", "arff_type": "numeric"})
        elif ctype == "string":
            item.update({"wire_type": "string", "arff_type": "string"})
        else:
            fail("CL_SCHEMA_INCOMPATIBLE", f"field {name} has unsupported C type {ctype!r}")
        if role == "label":
            label_count += 1
        fields.append(item)
    if label_count != 1:
        fail("CL_SCHEMA_INCOMPATIBLE", "dataset schema must have exactly one label field")
    label_field = dataset.label_field
    label = next((field for field in fields if field["name"] == label_field), None)
    if label is None or label["role"] != "label":
        fail("CL_SCHEMA_INCOMPATIBLE", "dataset label_field does not identify the label role")
    if label["arff_type"] != "nominal":
        fail("CL_SCHEMA_INCOMPATIBLE", "Java/Weka model packages require a nominal label")
    return fields, label_field, label["arff_type"]


def class_labels_for_dataset(dataset: Dataset) -> list[str]:
    fields, label_field, _ = contract_fields(dataset)
    label = next(field for field in fields if field["name"] == label_field)
    return list(label["arff_values"])


def positive_labels_for_dataset(_db, dataset: Dataset) -> list[str]:
    labels = class_labels_for_dataset(dataset)
    configured = DATASET_POSITIVE_LABELS.get(dataset.logical_id)
    if configured:
        positives = [label for label in labels if label in configured]
    else:
        common = {"anomaly", "malicious", "attack", "fraud", "1", "true", "yes", "high"}
        positives = [label for label in labels if label.lower() in common]
    if not positives:
        # 本地工具没有额外风险策略配置时，按 ARFF 标签域的最后一个类别作为风险类。
        positives = [labels[-1]]
    return positives


def risk_mapping_for_labels(labels: list[str], positives: list[str]) -> dict[str, str]:
    positive = set(positives)
    return {label: ("HIGH" if label in positive else "LOW") for label in labels}


def relation_for_dataset(dataset: Dataset) -> str:
    relation = re.sub(r"[^A-Za-z0-9._-]", "_", dataset.logical_id or "dataset")
    if not relation or not relation[0].isalpha():
        relation = "dataset_" + relation
    relation = relation[:128]
    if not _RELATION_RE.fullmatch(relation):
        fail("CL_SCHEMA_INCOMPATIBLE", "cannot derive a safe ARFF relation name")
    return relation


def load_dataset_rows(dataset: Dataset) -> tuple[list[dict[str, Any]], list[list[Any]]]:
    path = resolve_dataset_path(dataset.file_path)
    try:
        raw_fields, rows = read_all_rows(path)
    except Exception as exc:  # noqa: BLE001
        fail("CL_SCHEMA_INCOMPATIBLE", f"cannot read dataset file: {exc}")
    schema = dataset.fields_schema or []
    names = [str(field.get("name")) for field in schema]
    if [str(field.get("name")) for field in raw_fields] != names:
        fail("CL_SCHEMA_INCOMPATIBLE", "dataset file fields do not match the registered schema")
    if not rows:
        fail("CL_SCHEMA_INCOMPATIBLE", "dataset has no data rows")
    for row in rows:
        if len(row) != len(names):
            fail("CL_SCHEMA_INCOMPATIBLE", "dataset contains an incomplete row")
    dict_rows = [dict(zip(names, row)) for row in rows]
    return dict_rows, rows


def render_runtime_arff(dataset: Dataset) -> bytes:
    fields, _, _ = contract_fields(dataset)
    rows, _ = load_dataset_rows(dataset)
    row = rows[0]
    lines = [f"@relation {relation_for_dataset(dataset)}", ""]
    for field in fields:
        if field["arff_type"] == "nominal":
            domain = "{" + ",".join(arff_token(value) for value in field["arff_values"]) + "}"
            lines.append(f"@attribute {arff_token(field['name'])} {domain}")
        else:
            lines.append(f"@attribute {arff_token(field['name'])} {field['arff_type']}")
    lines.extend(["", "@data", ",".join(arff_token(row[field["name"]]) for field in fields), ""])
    return "\n".join(lines).encode("utf-8")


def features_from_row(row: dict[str, Any], label_field: str) -> dict[str, Any]:
    return {name: value for name, value in row.items() if name != label_field}
