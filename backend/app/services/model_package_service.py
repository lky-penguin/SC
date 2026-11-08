"""Portable model-package export/verification for frozen closed-loop-v1."""
from __future__ import annotations

import re
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.models.algorithm import Algorithm
from app.models.closed_loop import InstallationIdentity, ModelPackageExport
from app.models.dataset import Dataset
from app.models.model_version import ModelVersion
from app.paths import PROJECT_ROOT
from app.schemas.common import ok
from app.services.base import ServiceBase, ServiceError, service_call
from app.services.closed_loop_contract import (
    CONTRACT_VERSION,
    FIXTURE_LABEL,
    MANIFEST_FORMAT,
    MODEL_FORMAT,
    ContractViolation,
    canonical_content_sha256,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    validate_model_package_bytes,
)
from app.services.closed_loop_data import (
    class_labels_for_dataset,
    contract_fields,
    data_class_for_dataset,
    display_label_for_dataset,
    features_from_row,
    load_dataset_rows,
    positive_labels_for_dataset,
    relation_for_dataset,
    render_runtime_arff,
    risk_mapping_for_labels,
)
from app.services.constants import MODEL_STATUS_COMPLETED
from app.services.dataset_storage import resolve_dataset_path
from app.services.training_executor import build_model_save_path, execute_algorithm_service_predict

PACKAGE_ROOT = PROJECT_ROOT / "backend" / "storage" / "packages"
RUNTIME_TEMP_ROOT = PROJECT_ROOT / "backend" / "storage" / "runtime-temp"


def _utc_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _install_identity(db) -> InstallationIdentity:
    row = db.get(InstallationIdentity, 1)
    if row is None:
        import uuid
        row = InstallationIdentity(id=1, installation_id=str(uuid.uuid4()), created_at=datetime.now(timezone.utc))
        db.add(row)
        db.flush()
    return row


def _java_runtime_info() -> tuple[int, str]:
    try:
        version = subprocess.run(["java", "-version"], capture_output=True, text=True, timeout=20, check=True)
        version_text = version.stderr or version.stdout
        match = re.search(r'version\s+"([0-9]+)(?:\.([0-9]+))?', version_text)
        if not match:
            raise ValueError(f"unrecognized java version: {version_text.splitlines()[:3]}")
        major = int(match.group(1))
        weka_jar = PROJECT_ROOT / "backend" / "lib" / "pmwnb-service.jar"
        weka = subprocess.run(["java", "-cp", str(weka_jar), "weka.core.Version"], capture_output=True, text=True, timeout=30, check=True)
        weka_version = next((line.strip() for line in (weka.stdout or "").splitlines() if re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", line.strip())), "")
        if not weka_version:
            raise ValueError("Weka runtime returned no version")
        return major, weka_version
    except Exception as exc:  # noqa: BLE001
        raise ServiceError(503, f"CL_RUNTIME_INCOMPATIBLE: cannot prove Java/Weka runtime: {exc}") from exc


def _metric_number(metrics: dict[str, Any], key: str) -> float | int | None:
    value = metrics.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ServiceError(400, f"CL_SCHEMA_INVALID: evaluation metric {key} is not numeric")
    return value


def _metadata_for(db, model: ModelVersion, dataset: Dataset, algorithm: Algorithm, model_path: Path, runtime_bytes: bytes, package_id: str, export_event_id: str, exported_at: str, installation_id: str, data_class: str, display_label: str, model_bytes: bytes | None = None) -> dict[str, Any]:
    fields, label_field, _ = contract_fields(dataset)
    labels = class_labels_for_dataset(dataset)
    positives = positive_labels_for_dataset(db, dataset)
    rows, _ = load_dataset_rows(dataset)
    metrics = dict(model.evaluation_metrics or {})
    source = str(metrics.get("source") or "")
    if not source.startswith("java_"):
        raise ServiceError(400, "CL_SCHEMA_INVALID: model metrics are not from a real Java/Weka run")
    required_metrics = ("accuracy", "precision", "recall", "f1", "specificity", "g_mean", "risk_recall", "risk_f1")
    values = {key: _metric_number(metrics, key) for key in required_metrics}
    if any(value is None for value in values.values()):
        raise ServiceError(400, "CL_SCHEMA_INVALID: required deterministic Java metrics are unavailable; package export refused")
    num_instances = metrics.get("num_instances")
    if not isinstance(num_instances, int) or num_instances < 2 or num_instances != len(rows):
        raise ServiceError(400, "CL_SCHEMA_INVALID: Java num_instances does not prove the current dataset row count")
    num_attributes = metrics.get("num_attributes")
    num_classes = metrics.get("num_classes")
    if not isinstance(num_attributes, int) or num_attributes < 1 or num_classes != len(labels):
        raise ServiceError(400, "CL_SCHEMA_INVALID: Java attribute/class provenance is inconsistent")
    distribution = metrics.get("class_distribution")
    if distribution is not None:
        try:
            distribution_total = sum(int(item["count"]) for item in distribution)
        except Exception as exc:  # noqa: BLE001
            raise ServiceError(400, "CL_SCHEMA_INVALID: Java class distribution is malformed") from exc
        if distribution_total != len(rows):
            raise ServiceError(400, "CL_SCHEMA_INVALID: Java class distribution does not match dataset row count")
    metric_model_path = metrics.get("model_saved_to")
    metric_dataset_path = metrics.get("dataset")
    if metric_model_path and Path(str(metric_model_path)).resolve() != model_path.resolve():
        raise ServiceError(400, "CL_SCHEMA_INVALID: Java model path provenance does not match the stored model")
    dataset_path = resolve_dataset_path(dataset.file_path)
    if metric_dataset_path and Path(str(metric_dataset_path)).resolve() != Path(dataset_path).resolve():
        raise ServiceError(400, "CL_SCHEMA_INVALID: Java dataset path provenance does not match the selected dataset version")
    runtime_major, weka_version = _java_runtime_info()
    dataset_sha = sha256_file(str(dataset_path))
    model_sha = sha256_bytes(model_bytes) if model_bytes is not None else sha256_file(str(model_path))
    runtime_sha = sha256_bytes(runtime_bytes)
    metadata: dict[str, Any] = {
        "format": MODEL_FORMAT,
        "contract_version": CONTRACT_VERSION,
        "package_id": package_id,
        "idempotency_key": "0" * 64,
        "data_class": data_class,
        "display_label": display_label,
        "origin": {
            "app": "C",
            "installation_id": installation_id,
            "export_event_id": export_event_id,
            "exported_at": exported_at,
            "local_operator_ref": None,
        },
        "source": {
            "model_version_id": str(model.id),
            "dataset_version_id": str(dataset.id),
            "dataset_logical_id": dataset.logical_id,
            "dataset_version": dataset.version,
            "algorithm_id": str(algorithm.id),
            "algorithm_code": algorithm.code,
            "algorithm_display_name": algorithm.display_name,
        },
        "training": {
            "trained_at": _utc_z(model.trained_at),
            "published_at": _utc_z(model.trained_at),
            "training_run_id": f"c-model-{model.id}",
            "parameters": dict(model.training_parameters or {}),
            "dataset_sha256": dataset_sha,
            "dataset_record_count": len(rows),
            "split_policy": "cross_validation",
            "evaluation": {
                "metric_source": "java_pmwnb_cross_validation" if algorithm.code == "PMWNB" else "java_weka_cross_validation",
                "deterministic": True,
                "evaluation_method": "Java Weka stratified cross-validation (folds=min(10,n), seed=1)",
                "seed": 1,
                "fold_count": min(10, len(rows)),
                "metrics_available": True,
                "not_applicable_reason": None,
                "metrics": {
                    **{key: values[key] for key in required_metrics},
                    "num_instances": num_instances,
                    "num_attributes": num_attributes,
                    "num_classes": num_classes,
                },
            },
        },
        "runtime": {
            "model_binary_format": "weka-model-binary",
            "java_service_api": "local-java-predict-nb/v1",
            "algorithm_code": algorithm.code,
            "java_major": runtime_major,
            "weka_version": weka_version,
            "smoke_test_required": True,
            "prediction_input_keys": ["algorithm_code", "model_path", "arff_path", "features", "risk_labels"],
        },
        "dataset": {
            "logical_id": dataset.logical_id,
            "source_version_id": str(dataset.id),
            "version": dataset.version,
            "file_path": "runtime.arff",
            "file_sha256": runtime_sha,
            "format": "ARFF",
            "relation": relation_for_dataset(dataset),
            "field_order": [field["name"] for field in fields],
            "fields": fields,
            "label_field": label_field,
            "class_labels": labels,
            "positive_labels": positives,
            "risk_mapping": risk_mapping_for_labels(labels, positives),
            "default_thresholds": {"medium": 0.4, "high": 0.7},
            "record_count_in_runtime": 1,
        },
        "artifacts": [
            {"path": "model.model", "role": "model", "sha256": model_sha, "size_bytes": len(model_bytes) if model_bytes is not None else model_path.stat().st_size},
            {"path": "runtime.arff", "role": "runtime_context", "sha256": runtime_sha, "size_bytes": len(runtime_bytes)},
        ],
    }
    if data_class != "production":
        metadata["fixture_label"] = FIXTURE_LABEL
    return metadata

def _manifest_for(metadata: dict[str, Any], created_at: str, metadata_bytes: bytes, model_bytes: bytes, runtime_bytes: bytes) -> dict[str, Any]:
    files = [
        {"path": "metadata.json", "role": "metadata", "sha256": sha256_bytes(metadata_bytes), "size_bytes": len(metadata_bytes)},
        {"path": "model.model", "role": "model", "sha256": sha256_bytes(model_bytes), "size_bytes": len(model_bytes)},
        {"path": "runtime.arff", "role": "runtime_context", "sha256": sha256_bytes(runtime_bytes), "size_bytes": len(runtime_bytes)},
    ]
    manifest: dict[str, Any] = {
        "format": MANIFEST_FORMAT,
        "contract_version": CONTRACT_VERSION,
        "package_id": metadata["package_id"],
        "package_format": MODEL_FORMAT,
        "data_class": metadata["data_class"],
        "display_label": metadata["display_label"],
        "created_at": created_at,
        "files": files,
    }
    if metadata["data_class"] != "production":
        manifest["fixture_label"] = FIXTURE_LABEL
    return manifest


def _write_package_bytes(metadata_bytes: bytes, manifest_bytes: bytes, model_bytes: bytes, runtime_bytes: bytes) -> bytes:
    import io
    buffer = io.BytesIO()
    payloads = [
        ("metadata.json", metadata_bytes),
        ("manifest.json", manifest_bytes),
        ("model.model", model_bytes),
        ("runtime.arff", runtime_bytes),
    ]
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, payload in payloads:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(info, payload)
    return buffer.getvalue()


def _export_dict(row: ModelPackageExport) -> dict[str, Any]:
    return {
        "export_id": row.id,
        "package_id": row.package_id,
        "model_version_id": row.model_version_id,
        "dataset_version_id": row.dataset_version_id,
        "package_sha256": row.package_sha256,
        "metadata_sha256": row.metadata_sha256,
        "manifest_sha256": row.manifest_sha256,
        "model_sha256": row.model_sha256,
        "runtime_sha256": row.runtime_sha256,
        "idempotency_key": row.idempotency_key,
        "data_class": row.data_class,
        "display_label": row.display_label,
        "status": row.status,
        "exported_at": _utc_z(row.exported_at),
        "download_path": f"/api/v1/model-versions/{row.model_version_id}/package",
    }


class ModelPackageService(ServiceBase):
    def package_absolute_path(self, row: ModelPackageExport) -> Path:
        return PROJECT_ROOT / row.package_path.replace("\\", "/")

    def get_export_record(self, model_id: int) -> ModelPackageExport | None:
        return self.db.scalar(select(ModelPackageExport).where(ModelPackageExport.model_version_id == model_id))

    @service_call
    def export(self, model_id: int):
        import uuid
        model = self.db.get(ModelVersion, model_id)
        if model is None:
            raise ServiceError(404, "模型版本不存在")
        if model.status != MODEL_STATUS_COMPLETED:
            raise ServiceError(400, "只有训练完成的模型才能导出")
        dataset = self.db.get(Dataset, model.dataset_id)
        algorithm = self.db.get(Algorithm, model.algorithm_id)
        if dataset is None or algorithm is None:
            raise ServiceError(400, "CL_SOURCE_ID_MISSING: model dataset or algorithm is missing")
        existing = self.get_export_record(model_id)
        if existing is not None:
            path = self.package_absolute_path(existing)
            if not path.exists() or sha256_file(str(path)) != existing.package_sha256:
                raise ServiceError(409, "CL_IMMUTABLE_OBJECT_MUTATED: existing package bytes were changed")
            return ok(data=_export_dict(existing), message="CL_IDEMPOTENT_REPLAY: existing immutable package returned")
        model_path = Path(build_model_save_path(model.id, algorithm.code))
        if not model_path.exists():
            raise ServiceError(400, "CL_MODEL_LOAD_FAILED: stored Java model file is missing")
        runtime_bytes = render_runtime_arff(dataset)
        rows, _ = load_dataset_rows(dataset)
        fields, label_field, _ = contract_fields(dataset)
        positives = positive_labels_for_dataset(self.db, dataset)
        features = features_from_row(rows[0], label_field)
        temp_runtime = _runtime_temp_path(runtime_bytes)
        try:
            smoke = execute_algorithm_service_predict(algorithm.code, str(model_path), temp_runtime, features, positives)
        except Exception as exc:  # noqa: BLE001
            raise ServiceError(503, f"CL_RUNTIME_INCOMPATIBLE: packaged model/runtime smoke test failed: {exc}") from exc
        finally:
            _remove_runtime_temp(temp_runtime)
        model_bytes = model_path.read_bytes()
        package_id = str(uuid.uuid4())
        export_event_id = str(uuid.uuid4())
        exported_at = _utc_z(datetime.now(timezone.utc))
        installation = _install_identity(self.db)
        data_class = data_class_for_dataset(dataset)
        display_label = display_label_for_dataset(dataset, data_class)
        metadata = _metadata_for(
            self.db, model, dataset, algorithm, model_path, runtime_bytes, package_id,
            export_event_id, exported_at, installation.installation_id, data_class, display_label, model_bytes,
        )
        metadata["idempotency_key"] = canonical_content_sha256(metadata, remove_idempotency=True)
        metadata_bytes = canonical_json_bytes(metadata)
        manifest = _manifest_for(metadata, exported_at, metadata_bytes, model_bytes, runtime_bytes)
        manifest_bytes = canonical_json_bytes(manifest)
        package_bytes = _write_package_bytes(metadata_bytes, manifest_bytes, model_bytes, runtime_bytes)
        try:
            checked = validate_model_package_bytes(package_bytes)
        except ContractViolation as exc:
            raise ServiceError(400, f"{exc.code}: {exc.message}") from exc
        PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
        package_path = PACKAGE_ROOT / f"model_{model.id}_{package_id}.zip"
        if package_path.exists():
            raise ServiceError(409, "CL_IMMUTABLE_OBJECT_MUTATED: target package path already exists")
        package_path.write_bytes(package_bytes)
        relative_path = package_path.relative_to(PROJECT_ROOT).as_posix()
        row = ModelPackageExport(
            package_id=package_id,
            model_version_id=model.id,
            dataset_version_id=dataset.id,
            package_path=relative_path,
            package_sha256=checked["package_sha256"],
            metadata_sha256=checked["metadata_sha256"],
            manifest_sha256=sha256_bytes(manifest_bytes),
            model_sha256=sha256_bytes(model_bytes),
            runtime_sha256=sha256_bytes(runtime_bytes),
            idempotency_key=metadata["idempotency_key"],
            data_class=data_class,
            display_label=display_label,
            status="EXPORTED",
            exported_at=datetime.now(timezone.utc),
            metadata_json=metadata,
            manifest_json=manifest,
            smoke_result=smoke if isinstance(smoke, dict) else {"result": smoke},
        )
        try:
            self.db.add(row)
            self.commit()
        except Exception:
            package_path.unlink(missing_ok=True)
            raise
        return ok(data=_export_dict(row), message="模型已导出")

    @service_call
    def download(self, model_id: int):
        row = self.get_export_record(model_id)
        if row is None:
            raise ServiceError(404, "模型包尚未导出")
        path = self.package_absolute_path(row)
        if not path.exists() or sha256_file(str(path)) != row.package_sha256:
            raise ServiceError(409, "CL_IMMUTABLE_OBJECT_MUTATED: package file missing or modified")
        return path


def _runtime_temp_path(runtime_bytes: bytes) -> str:
    RUNTIME_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp = tempfile.NamedTemporaryFile(
        prefix="closed_loop_runtime_", suffix=".arff", dir=RUNTIME_TEMP_ROOT, delete=False,
    )
    try:
        temp.write(runtime_bytes)
        temp.close()
        return temp.name
    except Exception:
        temp.close()
        Path(temp.name).unlink(missing_ok=True)
        raise


def _remove_runtime_temp(path: str) -> None:
    """Best-effort cleanup for Java's short-lived Windows file handle."""
    target = Path(path)
    for attempt in range(5):
        try:
            target.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt < 4:
                time.sleep(0.15 * (attempt + 1))
