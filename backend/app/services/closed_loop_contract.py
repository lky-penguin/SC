"""Frozen closed-loop-v1 canonicalization and structural validation helpers.

This module deliberately depends only on the Python standard library. It is the C
application's local implementation boundary: no A/B Python module or database is
imported, and no wire value may carry an absolute filesystem path.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import stat
import zipfile
from datetime import datetime
from typing import Any

MODEL_FORMAT = "closed-loop.model-package/v1"
MANIFEST_FORMAT = "closed-loop.model-package.manifest/v1"
CONTRACT_VERSION = "closed-loop-v1"
FIXTURE_LABEL = "TEST_FIXTURE_ONLY_NOT_PRODUCTION"
ALLOWED_ALGORITHMS = {"PMWNB", "A2WNB", "MAWNB", "EMAWNB", "CAVWNB", "DIWNB", "KFDB", "FLNB", "FTAWNB"}
REQUIRED_PACKAGE_PATHS = {"metadata.json", "manifest.json", "model.model", "runtime.arff"}
OPTIONAL_PACKAGE_PATHS = {"README.txt"}
MAX_MEMBERS = 5
MAX_COMPRESSED = 67108864
MAX_UNCOMPRESSED = 268435456
MAX_MEMBER = 67108864
RISK_LEVELS = {"HIGH", "MEDIUM", "LOW"}
DATA_CLASSES = {"production", "test_fixture", "demo"}

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA_RE = re.compile(r"^[a-f0-9]{64}$")
_TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{3}|\.[0-9]{6})?Z$")
_FIELD_RE = re.compile(r"^[^\s,{}@]+$")
_RELATION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")


class ContractViolation(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def fail(code: str, message: str) -> None:
    raise ContractViolation(code, message)


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_loads(raw: bytes | str) -> Any:
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if text.startswith("\ufeff"):
            raise ValueError("UTF-8 BOM is forbidden on the wire")
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except ContractViolation:
        raise
    except Exception as exc:  # noqa: BLE001
        fail("CL_SCHEMA_INVALID", f"JSON cannot be parsed: {exc}")


def _validate_json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value) or (value == 0.0 and math.copysign(1.0, value) < 0):
            fail("CL_SCHEMA_INVALID", f"{path}: non-finite or negative zero number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                fail("CL_SCHEMA_INVALID", f"{path}: object key is not a string")
            _validate_json_value(item, f"{path}.{key}")
        return
    fail("CL_SCHEMA_INVALID", f"{path}: unsupported JSON value type {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    _validate_json_value(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_content_sha256(document: dict[str, Any], *, remove_idempotency: bool = False) -> str:
    payload = dict(document)
    payload.pop("integrity", None)
    if remove_idempotency:
        payload.pop("idempotency_key", None)
    return sha256_bytes(canonical_json_bytes(payload))


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        fail(code, message)


def is_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not _TS_RE.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_timestamp(value: Any, field: str) -> None:
    _require(is_timestamp(value), "CL_SCHEMA_INVALID", f"{field} must be a UTC ISO-8601 timestamp ending in Z")


def validate_uuid(value: Any, field: str) -> None:
    _require(isinstance(value, str) and bool(_UUID_RE.fullmatch(value)), "CL_SCHEMA_INVALID", f"{field} must be a lowercase UUID v4")


def validate_opaque_id(value: Any, field: str) -> None:
    _require(isinstance(value, str) and bool(_OPAQUE_RE.fullmatch(value)), "CL_SCHEMA_INVALID", f"{field} must be a stable opaque ID")


def validate_sha256(value: Any, field: str) -> None:
    _require(isinstance(value, str) and bool(_SHA_RE.fullmatch(value)), "CL_SCHEMA_INVALID", f"{field} must be lowercase SHA-256")


def validate_archive_name(name: str) -> None:
    if not isinstance(name, str) or not name:
        fail("CL_ARCHIVE_UNSAFE_PATH", "archive member name is empty")
    if "\\" in name or ":" in name or name.startswith("/") or name.endswith("/"):
        fail("CL_ARCHIVE_UNSAFE_PATH", f"unsafe archive member name: {name!r}")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        fail("CL_ARCHIVE_UNSAFE_PATH", f"unsafe archive member segment: {name!r}")


def _zip_members(archive: zipfile.ZipFile) -> tuple[dict[str, zipfile.ZipInfo], int, int]:
    infos = archive.infolist()
    _require(len(infos) <= MAX_MEMBERS, "CL_ARCHIVE_LIMIT", "model package has too many members")
    members: dict[str, zipfile.ZipInfo] = {}
    folded: set[str] = set()
    total_compressed = 0
    total_uncompressed = 0
    for info in infos:
        name = info.filename
        validate_archive_name(name)
        _require(not info.is_dir(), "CL_ARCHIVE_UNSAFE_PATH", f"directory entries are forbidden: {name}")
        key = name.casefold()
        _require(key not in folded, "CL_ARCHIVE_DUPLICATE_MEMBER", f"duplicate/case-colliding member: {name}")
        folded.add(key)
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            fail("CL_ARCHIVE_SYMLINK", f"symlink member forbidden: {name}")
        if mode and not stat.S_ISREG(mode):
            fail("CL_ARCHIVE_SYMLINK", f"special file member forbidden: {name}")
        _require(info.file_size <= MAX_MEMBER, "CL_ARCHIVE_LIMIT", f"member too large: {name}")
        total_compressed += info.compress_size
        total_uncompressed += info.file_size
        members[name] = info
    _require(total_compressed <= MAX_COMPRESSED, "CL_ARCHIVE_LIMIT", "compressed package too large")
    _require(total_uncompressed <= MAX_UNCOMPRESSED, "CL_ARCHIVE_LIMIT", "uncompressed package too large")
    return members, total_compressed, total_uncompressed

def validate_model_package_bytes(raw: bytes) -> dict[str, Any]:
    _require(len(raw) <= MAX_COMPRESSED, "CL_ARCHIVE_LIMIT", "package bytes exceed compressed limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw), "r")
    except zipfile.BadZipFile as exc:
        fail("CL_SCHEMA_INVALID", f"model package is not a valid ZIP: {exc}")
    with archive:
        members, _, _ = _zip_members(archive)
        names = set(members)
        _require(REQUIRED_PACKAGE_PATHS <= names, "CL_SCHEMA_INVALID", "model package is missing required members")
        _require(names <= REQUIRED_PACKAGE_PATHS | OPTIONAL_PACKAGE_PATHS, "CL_SCHEMA_INVALID", "model package contains undeclared members")
        manifest = strict_json_loads(archive.read("manifest.json"))
        metadata = strict_json_loads(archive.read("metadata.json"))
        _validate_manifest(manifest, metadata, members)
        _validate_model_metadata(metadata)
        expected = {item["path"]: item for item in manifest["files"]}
        _require(set(expected) == names - {"manifest.json"}, "CL_SCHEMA_INVALID", "manifest member list does not match ZIP payload")
        for path, item in expected.items():
            payload = archive.read(path)
            _require(sha256_bytes(payload) == item["sha256"], "CL_HASH_MISMATCH", f"member hash mismatch: {path}")
            _require(len(payload) == item["size_bytes"], "CL_HASH_MISMATCH", f"member size mismatch: {path}")
        metadata_hash = sha256_bytes(archive.read("metadata.json"))
        artifact_map = {item["path"]: item for item in metadata["artifacts"]}
        for path in ("model.model", "runtime.arff"):
            _require(path in artifact_map, "CL_SCHEMA_INVALID", f"metadata artifacts missing {path}")
            _require(artifact_map[path]["sha256"] == expected[path]["sha256"], "CL_HASH_MISMATCH", f"metadata/manifest hash disagree for {path}")
        _require(metadata["dataset"]["file_sha256"] == expected["runtime.arff"]["sha256"], "CL_HASH_MISMATCH", "runtime ARFF hash does not match dataset contract")
    return {"metadata": metadata, "manifest": manifest, "package_sha256": sha256_bytes(raw), "metadata_sha256": metadata_hash}


def _validate_manifest(manifest: Any, metadata: Any, members: dict[str, zipfile.ZipInfo]) -> None:
    _require(isinstance(manifest, dict), "CL_SCHEMA_INVALID", "manifest must be an object")
    required = {"format", "contract_version", "package_id", "package_format", "data_class", "display_label", "created_at", "files"}
    _require(set(manifest) >= required, "CL_SCHEMA_INVALID", "manifest missing required fields")
    _require(manifest["format"] == MANIFEST_FORMAT, "CL_UNSUPPORTED_FORMAT", "unsupported manifest format")
    _require(manifest["contract_version"] == CONTRACT_VERSION and manifest["package_format"] == MODEL_FORMAT, "CL_UNSUPPORTED_FORMAT", "unsupported contract/package version")
    validate_uuid(manifest["package_id"], "manifest.package_id")
    validate_timestamp(manifest["created_at"], "manifest.created_at")
    _require(manifest["data_class"] in DATA_CLASSES, "CL_SCHEMA_INVALID", "invalid data_class")
    _require(isinstance(manifest["display_label"], str) and 1 <= len(manifest["display_label"]) <= 80, "CL_SCHEMA_INVALID", "invalid display_label")
    if manifest["data_class"] != "production":
        _require(manifest.get("fixture_label") == FIXTURE_LABEL, "CL_SCHEMA_INVALID", "non-production manifest requires fixture_label")
        _require(manifest["display_label"].upper().startswith(("TEST", "DEMO")), "CL_SCHEMA_INVALID", "non-production display label must begin TEST or DEMO")
    files = manifest.get("files")
    _require(isinstance(files, list) and 3 <= len(files) <= 4, "CL_SCHEMA_INVALID", "manifest.files must contain 3-4 items")
    seen: set[str] = set()
    roles = {"metadata.json": "metadata", "model.model": "model", "runtime.arff": "runtime_context", "README.txt": "readme"}
    for item in files:
        _require(isinstance(item, dict), "CL_SCHEMA_INVALID", "manifest file entry must be an object")
        path = item.get("path")
        _require(path in roles, "CL_SCHEMA_INVALID", "manifest contains an undeclared member path")
        _require(path not in seen, "CL_ARCHIVE_DUPLICATE_MEMBER", "manifest lists a member more than once")
        seen.add(path)
        _require(item.get("role") == roles[path], "CL_SCHEMA_INVALID", f"invalid role for {path}")
        validate_sha256(item.get("sha256"), f"manifest.files[{path}].sha256")
        _require(isinstance(item.get("size_bytes"), int) and 1 <= item["size_bytes"] <= MAX_MEMBER, "CL_SCHEMA_INVALID", f"invalid size for {path}")
        _require(path in members, "CL_SCHEMA_INVALID", f"manifest member missing from ZIP: {path}")
    _require({"metadata.json", "model.model", "runtime.arff"} <= seen, "CL_SCHEMA_INVALID", "manifest missing required files")
    _require(isinstance(metadata, dict), "CL_SCHEMA_INVALID", "metadata must be an object")
    _require(metadata.get("package_id") == manifest["package_id"], "CL_IMMUTABLE_OBJECT_MUTATED", "manifest/metadata package IDs disagree")
    _require(metadata.get("data_class") == manifest["data_class"] and metadata.get("display_label") == manifest["display_label"], "CL_IMMUTABLE_OBJECT_MUTATED", "manifest/metadata classification disagrees")


def _validate_field_contract(fields: Any, field_order: Any, label_field: Any, class_labels: Any, positives: Any, risk_mapping: Any) -> None:
    _require(isinstance(field_order, list) and len(field_order) >= 2 and len(set(field_order)) == len(field_order), "CL_SCHEMA_INVALID", "field_order must be a unique array of at least two names")
    _require(isinstance(fields, list) and len(fields) == len(field_order), "CL_SCHEMA_INVALID", "fields length must match field_order")
    names: list[str] = []
    label_count = 0
    for field in fields:
        _require(isinstance(field, dict), "CL_SCHEMA_INVALID", "field must be an object")
        name = field.get("name")
        _require(isinstance(name, str) and bool(_FIELD_RE.fullmatch(name)) and len(name) <= 128, "CL_SCHEMA_INVALID", "invalid field name")
        names.append(name)
        _require(field.get("wire_type") in {"integer", "number", "string", "boolean", "nominal"}, "CL_SCHEMA_INVALID", f"invalid wire_type for {name}")
        _require(isinstance(field.get("arff_type"), str) and field["arff_type"], "CL_SCHEMA_INVALID", f"invalid arff_type for {name}")
        _require(field.get("role") in {"feature", "label", "metadata", "identifier"}, "CL_SCHEMA_INVALID", f"invalid role for {name}")
        if field.get("role") == "label":
            label_count += 1
        if field.get("arff_type") == "nominal":
            _require(isinstance(field.get("arff_values"), list) and len(field["arff_values"]) >= 1 and len(set(field["arff_values"])) == len(field["arff_values"]), "CL_SCHEMA_INVALID", f"nominal field {name} requires a unique arff_values domain")
    _require(names == field_order, "CL_SCHEMA_INVALID", "field_order must equal the ordered fields[].name values")
    _require(label_count == 1, "CL_SCHEMA_INVALID", "exactly one field must have role label")
    _require(label_field in names, "CL_SCHEMA_INVALID", "label_field is absent from field_order")
    label = next(field for field in fields if field["name"] == label_field)
    _require(label.get("role") == "label" and label.get("arff_type") == "nominal", "CL_SCHEMA_INCOMPATIBLE", "label field must be nominal")
    _require(isinstance(class_labels, list) and len(class_labels) >= 2 and len(set(class_labels)) == len(class_labels), "CL_SCHEMA_INVALID", "class_labels must be unique with at least two values")
    _require(label.get("arff_values") == class_labels, "CL_SCHEMA_INCOMPATIBLE", "label domain does not match class_labels in order")
    _require(isinstance(positives, list) and positives and len(set(positives)) == len(positives), "CL_SCHEMA_INVALID", "positive_labels must be non-empty and unique")
    _require(set(positives) <= set(class_labels), "CL_SCHEMA_INCOMPATIBLE", "positive_labels must be a subset of class_labels")
    _require(isinstance(risk_mapping, dict) and set(risk_mapping) == set(class_labels), "CL_SCHEMA_INVALID", "risk_mapping must cover exactly every class label")
    _require(all(value in RISK_LEVELS for value in risk_mapping.values()), "CL_SCHEMA_INVALID", "invalid risk level")

def _validate_model_metadata(metadata: dict[str, Any]) -> None:
    required = {"format", "contract_version", "package_id", "idempotency_key", "data_class", "display_label", "origin", "source", "training", "runtime", "dataset", "artifacts"}
    _require(set(metadata) >= required, "CL_SCHEMA_INVALID", "metadata missing required fields")
    _require(metadata["format"] == MODEL_FORMAT and metadata["contract_version"] == CONTRACT_VERSION, "CL_UNSUPPORTED_FORMAT", "unsupported metadata format/version")
    validate_uuid(metadata["package_id"], "metadata.package_id")
    validate_sha256(metadata["idempotency_key"], "metadata.idempotency_key")
    _require(metadata["data_class"] in DATA_CLASSES, "CL_SCHEMA_INVALID", "invalid data_class")
    _require(isinstance(metadata["display_label"], str) and 1 <= len(metadata["display_label"]) <= 80, "CL_SCHEMA_INVALID", "invalid display_label")
    if metadata["data_class"] != "production":
        _require(metadata.get("fixture_label") == FIXTURE_LABEL, "CL_SCHEMA_INVALID", "non-production metadata requires fixture_label")
        _require(metadata["display_label"].upper().startswith(("TEST", "DEMO")), "CL_SCHEMA_INVALID", "non-production display label must begin TEST or DEMO")
    expected_idem = canonical_content_sha256(metadata, remove_idempotency=True)
    _require(metadata["idempotency_key"] == expected_idem, "CL_HASH_MISMATCH", "metadata idempotency key mismatch")

    origin = metadata.get("origin")
    _require(isinstance(origin, dict) and origin.get("app") == "C", "CL_SCHEMA_INVALID", "metadata origin.app must be C")
    validate_uuid(origin.get("installation_id"), "metadata.origin.installation_id")
    validate_uuid(origin.get("export_event_id"), "metadata.origin.export_event_id")
    validate_timestamp(origin.get("exported_at"), "metadata.origin.exported_at")

    source = metadata.get("source")
    _require(isinstance(source, dict), "CL_SCHEMA_INVALID", "metadata.source must be an object")
    for key in ("model_version_id", "dataset_version_id", "dataset_logical_id", "algorithm_id"):
        validate_opaque_id(source.get(key), f"metadata.source.{key}")
    _require(isinstance(source.get("dataset_version"), int) and source["dataset_version"] >= 1, "CL_SCHEMA_INVALID", "invalid source.dataset_version")
    _require(source.get("algorithm_code") in ALLOWED_ALGORITHMS, "CL_ALGORITHM_INCOMPATIBLE", "unsupported algorithm")
    _require(isinstance(source.get("algorithm_display_name"), str) and source["algorithm_display_name"], "CL_SCHEMA_INVALID", "missing algorithm display name")

    training = metadata.get("training")
    _require(isinstance(training, dict), "CL_SCHEMA_INVALID", "metadata.training must be an object")
    validate_timestamp(training.get("trained_at"), "metadata.training.trained_at")
    validate_timestamp(training.get("published_at"), "metadata.training.published_at")
    validate_opaque_id(training.get("training_run_id"), "metadata.training.training_run_id")
    _require(isinstance(training.get("parameters"), dict), "CL_SCHEMA_INVALID", "training.parameters must be an object")
    validate_sha256(training.get("dataset_sha256"), "metadata.training.dataset_sha256")
    _require(isinstance(training.get("dataset_record_count"), int) and training["dataset_record_count"] >= 1, "CL_SCHEMA_INVALID", "invalid dataset_record_count")
    _require(training.get("split_policy") in {"training_only", "documented_holdout", "cross_validation"}, "CL_SCHEMA_INVALID", "invalid split_policy")
    evaluation = training.get("evaluation")
    _require(isinstance(evaluation, dict), "CL_SCHEMA_INVALID", "training.evaluation must be an object")
    _require(evaluation.get("metric_source") in {"java_pmwnb_cross_validation", "java_weka_cross_validation"}, "CL_SCHEMA_INVALID", "metrics must come from Java/Weka cross-validation")
    _require(evaluation.get("deterministic") is True, "CL_SCHEMA_INVALID", "evaluation must be deterministic")
    _require(isinstance(evaluation.get("seed"), int), "CL_SCHEMA_INVALID", "evaluation.seed must be an integer")
    _require(isinstance(evaluation.get("fold_count"), int) and evaluation["fold_count"] >= 2, "CL_SCHEMA_INVALID", "evaluation.fold_count must be at least 2")
    _require(isinstance(evaluation.get("metrics_available"), bool), "CL_SCHEMA_INVALID", "metrics_available must be boolean")
    metrics = evaluation.get("metrics")
    metric_names = {"accuracy", "precision", "recall", "f1", "specificity", "g_mean", "risk_recall", "risk_f1", "num_instances", "num_attributes", "num_classes"}
    _require(isinstance(metrics, dict) and set(metrics) == metric_names, "CL_SCHEMA_INVALID", "evaluation.metrics has an invalid shape")
    for name in metric_names - {"num_instances", "num_attributes", "num_classes"}:
        value = metrics[name]
        _require(value is None or (isinstance(value, (int, float)) and math.isfinite(float(value)) and 0 <= value <= 1), "CL_SCHEMA_INVALID", f"invalid metric {name}")
    for name in ("num_instances", "num_attributes", "num_classes"):
        value = metrics[name]
        _require(value is None or (isinstance(value, int) and value >= 0), "CL_SCHEMA_INVALID", f"invalid metric count {name}")

    runtime = metadata.get("runtime")
    _require(isinstance(runtime, dict), "CL_SCHEMA_INVALID", "metadata.runtime must be an object")
    _require(runtime.get("model_binary_format") == "weka-model-binary", "CL_RUNTIME_INCOMPATIBLE", "unsupported model binary format")
    _require(runtime.get("java_service_api") == "local-java-predict-nb/v1", "CL_RUNTIME_INCOMPATIBLE", "unsupported Java service API")
    _require(runtime.get("algorithm_code") in ALLOWED_ALGORITHMS, "CL_ALGORITHM_INCOMPATIBLE", "unsupported runtime algorithm")
    _require(isinstance(runtime.get("java_major"), int) and runtime["java_major"] >= 8, "CL_RUNTIME_INCOMPATIBLE", "invalid Java major")
    _require(isinstance(runtime.get("weka_version"), str) and runtime["weka_version"], "CL_RUNTIME_INCOMPATIBLE", "missing Weka version")
    _require(runtime.get("smoke_test_required") is True, "CL_RUNTIME_INCOMPATIBLE", "smoke test must be required")
    _require(runtime.get("prediction_input_keys") == ["algorithm_code", "model_path", "arff_path", "features", "risk_labels"], "CL_RUNTIME_INCOMPATIBLE", "prediction input keys do not match local Java API")

    dataset = metadata.get("dataset")
    _require(isinstance(dataset, dict), "CL_SCHEMA_INVALID", "metadata.dataset must be an object")
    validate_opaque_id(dataset.get("logical_id"), "metadata.dataset.logical_id")
    validate_opaque_id(dataset.get("source_version_id"), "metadata.dataset.source_version_id")
    _require(isinstance(dataset.get("version"), int) and dataset["version"] >= 1, "CL_SCHEMA_INVALID", "invalid dataset.version")
    _require(dataset.get("file_path") == "runtime.arff", "CL_SCHEMA_INCOMPATIBLE", "dataset.file_path must be runtime.arff")
    validate_sha256(dataset.get("file_sha256"), "metadata.dataset.file_sha256")
    _require(dataset.get("format") == "ARFF", "CL_SCHEMA_INCOMPATIBLE", "runtime context must be ARFF")
    _require(isinstance(dataset.get("relation"), str) and bool(_RELATION_RE.fullmatch(dataset["relation"])), "CL_SCHEMA_INVALID", "invalid ARFF relation name")
    _validate_field_contract(
        dataset.get("fields"), dataset.get("field_order"), dataset.get("label_field"),
        dataset.get("class_labels"), dataset.get("positive_labels"), dataset.get("risk_mapping"),
    )
    thresholds = dataset.get("default_thresholds")
    _require(isinstance(thresholds, dict) and set(thresholds) == {"medium", "high"}, "CL_SCHEMA_INVALID", "invalid default_thresholds shape")
    medium, high = thresholds.get("medium"), thresholds.get("high")
    _require(isinstance(medium, (int, float)) and isinstance(high, (int, float)) and 0 <= medium < high <= 1, "CL_SCHEMA_INVALID", "thresholds require 0 <= medium < high <= 1")
    _require(isinstance(dataset.get("record_count_in_runtime"), int) and dataset["record_count_in_runtime"] >= 1, "CL_SCHEMA_INVALID", "runtime must contain at least one row")
    _require(dataset["logical_id"] == source["dataset_logical_id"], "CL_SOURCE_ID_MISSING", "dataset logical IDs disagree")
    _require(dataset["source_version_id"] == source["dataset_version_id"], "CL_SOURCE_ID_MISSING", "dataset version IDs disagree")
    _require(dataset["version"] == source["dataset_version"], "CL_SOURCE_ID_MISSING", "dataset version numbers disagree")
    _require(runtime["algorithm_code"] == source["algorithm_code"], "CL_ALGORITHM_INCOMPATIBLE", "runtime/source algorithm codes disagree")

    artifacts = metadata.get("artifacts")
    _require(isinstance(artifacts, list) and 2 <= len(artifacts) <= 3, "CL_SCHEMA_INVALID", "metadata.artifacts must contain 2-3 entries")
    artifact_roles = {"model.model": "model", "runtime.arff": "runtime_context", "README.txt": "readme"}
    seen: set[str] = set()
    for item in artifacts:
        _require(isinstance(item, dict) and item.get("path") in artifact_roles, "CL_SCHEMA_INVALID", "invalid artifact path")
        _require(item["path"] not in seen, "CL_SCHEMA_INVALID", "duplicate artifact path")
        seen.add(item["path"])
        _require(item.get("role") == artifact_roles[item["path"]], "CL_SCHEMA_INVALID", "invalid artifact role")
        validate_sha256(item.get("sha256"), f"metadata.artifacts[{item['path']}].sha256")
        _require(isinstance(item.get("size_bytes"), int) and 1 <= item["size_bytes"] <= MAX_MEMBER, "CL_SCHEMA_INVALID", "invalid artifact size")
    _require({"model.model", "runtime.arff"} <= seen, "CL_SCHEMA_INVALID", "model/runtime artifacts are required")
