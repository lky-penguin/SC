from __future__ import annotations
import os
import csv
from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from app.models.dataset import Dataset
from app.models.dataset_revision import DatasetRevision
from app.models.model_version import ModelVersion
from app.schemas.common import ok
from app.services.base import ServiceBase, ServiceError, service_call
from app.services.constants import (
    DATASET_FILE_PATH_MAX_LEN,
    DATASET_LABEL_FIELD_MAX_LEN,
    DATASET_LOGICAL_ID_MAX_LEN,
    DATASET_STATUS_ACTIVE,
    DATASET_STATUS_INACTIVE,
)
from app.services.dataset_iteration import (
    CHANGE_TYPE_APPEND_ROWS,
    CHANGE_TYPE_CREATE,
    CHANGE_TYPE_METADATA,
    CHANGE_TYPE_REPLACE_FILE,
    CHANGE_TYPES,
    MODE_IN_PLACE,
    MODE_NEW_VERSION,
    IterationDecision,
    resolve_iteration_policy,
)
from app.services.dataset_presenter import dataset_to_dict, revision_to_dict
from app.services.dataset_storage import (
    canonical_dataset_path,
    count_dataset_records,
    dataset_paths_same,
    iteration_target_path,
    resolve_dataset_path,
    save_uploaded_dataset,
    validate_dataset_file_path,
)
from app.utils.dataset_file_reader import (
    build_fields_schema,
    detect_format,
    parse_dataset_bytes,
    read_all_rows,
    read_dataset_fields,
    read_sample_rows,
    write_dataset_file,
)
from app.utils.runtime import get_logger
from app.utils.serialization import paginate
from app.utils.validation import (
    validate_fields_schema,
    validate_length,
    validate_required,
)
logger = get_logger("dataset")
class DatasetService(ServiceBase):
    def _get(self, dataset_id: int) -> Dataset:
        dataset = self.db.get(Dataset, dataset_id)
        if dataset is None:
            raise ServiceError(404, "数据集不存在")
        return dataset
    @staticmethod
    def _validate_file_path(file_path: str) -> None:
        err = validate_length(file_path, "file_path", DATASET_FILE_PATH_MAX_LEN)
        if err:
            raise ServiceError(400, err)
        path_err = validate_dataset_file_path(file_path)
        if path_err:
            raise ServiceError(400, path_err)
    @staticmethod
    def _schema_from_uploaded_fields(
        fields: list[dict], label_field: str, *, subject: str
    ) -> list[dict]:
        if not fields:  # 解析失败基本是上传文件问题
            raise ServiceError(400, f"{subject}没有解析出任何字段")
        names = [str(field.get("name", "")) for field in fields]
        if label_field not in names:
            raise ServiceError(
                400,
                f"标签字段 {label_field} 不存在于{subject}字段中，可用字段: {', '.join(names[:10])}",
            )
        return build_fields_schema(fields, label_field)
    @staticmethod
    def _schema_matches(
        left: list[dict] | None,
        right: list[dict] | None,
        *,
        preserve_enum_order: bool = True,
    ) -> bool:
        left_fields = left or []
        right_fields = right or []
        if len(left_fields) != len(right_fields):
            return False
        for current, other in zip(left_fields, right_fields):
            if (
                str(current.get("name", "")) != str(other.get("name", ""))
                or str(current.get("role", "feature"))
                != str(other.get("role", "feature"))
                or str(current.get("type", "")) != str(other.get("type", ""))
            ):
                return False
            current_enum = [str(value) for value in (current.get("enum_values") or [])]
            other_enum = [str(value) for value in (other.get("enum_values") or [])]
            if not preserve_enum_order:
                current_enum.sort()
                other_enum.sort()
            if current_enum != other_enum:
                return False
        return True
    def _read_replacement_schema(
        self, file_path: str, label_field: str
    ) -> list[dict]:
        try:
            fields = read_dataset_fields(resolve_dataset_path(file_path))
        except (OSError, ValueError, csv.Error) as exc:
            raise ServiceError(400, f"替换文件解析失败: {exc}") from exc
        return self._schema_from_uploaded_fields(fields, label_field, subject="替换文件")
    @staticmethod
    def _cleanup_unregistered_upload(file_path: str) -> None:  # 清理没登记的文件
        if validate_dataset_file_path(file_path) is not None:
            return
        try:
            path = resolve_dataset_path(file_path)
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            logger.warning("清理未登记上传文件失败: %s", file_path)
    def _next_version(self, logical_id: str) -> int:
        max_version = self.db.scalar(
            select(func.max(Dataset.version)).where(Dataset.logical_id == logical_id)
        ) or 0  # 靠唯一约束兜底
        return int(max_version) + 1
    def _is_referenced(self, dataset_id: int) -> bool:
        count = self.db.scalar(
            select(func.count()).select_from(ModelVersion).where(
                ModelVersion.dataset_id == dataset_id
            )
        )
        return bool(count)
    def _record_revision(
        self,
        *,
        dataset: Dataset,
        change_type: str,
        decision: IterationDecision,
        summary: str | None,
        detail: dict | None,
        result_dataset_id: int | None,
        created_at: datetime,
    ) -> None:
        self.db.add(
            DatasetRevision(
                logical_id=dataset.logical_id,
                dataset_id=dataset.id,
                change_type=change_type,
                is_breaking=decision.is_breaking,
                mode=decision.mode,
                result_dataset_id=result_dataset_id,
                reason=decision.reason,
                summary=summary,
                detail=detail,
                created_at=created_at,
            )
        )
    def _to_dict(self, dataset: Dataset) -> dict:  # 序列化数据集
        return dataset_to_dict(
            dataset,
            record_count=count_dataset_records(dataset.file_path),
            referenced=self._is_referenced(dataset.id),
        )
    def _to_dict_many(self, datasets: list[Dataset]) -> list[dict]:
        ids = [item.id for item in datasets]
        referenced_ids = set(
            self.db.scalars(
                select(ModelVersion.dataset_id)
                .where(ModelVersion.dataset_id.in_(ids))
                .distinct()
            ).all()
        )  # 列表页一次查完，防止循环查库
        record_counts = {}
        for item in datasets:
            if item.file_path not in record_counts:
                record_counts[item.file_path] = count_dataset_records(item.file_path)
        return [
            dataset_to_dict(
                item,
                record_count=record_counts[item.file_path],
                referenced=item.id in referenced_ids,
            )
            for item in datasets
        ]
    @service_call
    def get_list(
        self,
        page: int = 1,
        page_size: int = 10,
    ):
        stmt = select(Dataset).order_by(Dataset.logical_id, Dataset.version)
        result = paginate(self.db, stmt, page, page_size)
        result["items"] = self._to_dict_many(result["items"])
        return ok(data=result)
    @service_call
    def get(self, dataset_id: int):
        return ok(data=self._to_dict(self._get(dataset_id)))
    @service_call
    def get_versions(self, dataset_id: int):
        dataset = self._get(dataset_id)
        versions = self.db.scalars(
            select(Dataset)
            .where(Dataset.logical_id == dataset.logical_id)
            .order_by(Dataset.version.desc())
        ).all()
        return ok(data={"items": self._to_dict_many(versions)})
    @staticmethod
    def _generated_logical_id() -> str:  # 生成内部数据集标识
        return f"ds_{uuid4().hex}"
    @staticmethod
    def _default_label_field(fields_schema: list[dict]) -> str:  # 取最后一列为标签字段
        if not fields_schema:
            raise ServiceError(400, "数据集没有可用字段")
        last = fields_schema[-1]
        label_field = str(last.get("name", "")).strip() if isinstance(last, dict) else ""
        if not label_field:
            raise ServiceError(400, "无法识别标签字段")
        return label_field
    @service_call
    def create(
        self,
        *,
        name: str,
        file_path: str,
        fields_schema: list[dict],
        label_field: str | None = None,
        logical_id: str | None = None,
    ):
        name = (name or "").strip()
        label_field = (label_field or self._default_label_field(fields_schema)).strip()
        logical_id = logical_id or self._generated_logical_id()
        err = validate_required(
            {"name": name, "file_path": file_path, "label_field": label_field},
            ("name", "file_path", "label_field"),
        )
        if err:
            raise ServiceError(400, err)
        err = validate_length(logical_id, "logical_id", DATASET_LOGICAL_ID_MAX_LEN)
        if err:
            raise ServiceError(400, err)
        self._validate_file_path(file_path)
        file_path = canonical_dataset_path(file_path)
        err = validate_length(label_field, "label_field", DATASET_LABEL_FIELD_MAX_LEN)
        if err:
            raise ServiceError(400, err)
        err = validate_fields_schema(fields_schema, label_field)
        if err:
            raise ServiceError(400, err)
        decision = resolve_iteration_policy(CHANGE_TYPE_CREATE, referenced=False)
        self.db.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(logical_id)))
        )
        now = datetime.now(timezone.utc)
        dataset = Dataset(
            logical_id=logical_id,
            name=name,
            version=self._next_version(logical_id),
            file_path=file_path,
            fields_schema=fields_schema,
            label_field=label_field,
            uploaded_at=now,
            status=DATASET_STATUS_ACTIVE,
            change_type=CHANGE_TYPE_CREATE,
            base_version_id=None,
            is_breaking=decision.is_breaking,
        )
        self.db.add(dataset)
        self.db.flush()
        self._record_revision(
            dataset=dataset,
            change_type=CHANGE_TYPE_CREATE,
            decision=decision,
            summary=f"登记数据集 {name} v{dataset.version}",
            detail=None,
            result_dataset_id=dataset.id,
            created_at=now,
        )
        data = self._to_dict(dataset)
        self.commit()
        return ok(data=data, message="数据集上传成功")
    @service_call
    def upload_from_file(
        self,
        name: str,
        filename: str,
        file_bytes: bytes,
    ):  # 上传数据集文件
        fmt = detect_format(filename)
        if fmt == "unknown":
            raise ServiceError(400, "仅支持.arff/.csv格式文件")
        try:
            relative_path = save_uploaded_dataset(filename, file_bytes)
        except ValueError as exc:
            raise ServiceError(400, str(exc)) from exc
        try:
            saved_path = resolve_dataset_path(relative_path)
            try:
                fields = read_dataset_fields(saved_path)
            except (OSError, ValueError, csv.Error) as exc:
                raise ServiceError(400, f"文件解析失败: {exc}") from exc
            label_field = self._default_label_field(fields)
            fields_schema = self._schema_from_uploaded_fields(
                fields, label_field, subject="文件"
            )
            response = self.create(
                name=name,
                file_path=relative_path,
                fields_schema=fields_schema,
                label_field=label_field,
            )
            if response.code != 0:
                raise ServiceError(response.code, response.message)
        except Exception:
            self._cleanup_unregistered_upload(relative_path)
            raise
        return response
    def _revise(
        self,
        dataset_id: int,
        change_type: str,
        *,
        file_path: str | None = None,
        fields_schema: list[dict] | None = None,
        label_field: str | None = None,
        name: str | None = None,
        summary: str | None = None,
        detail: dict | None = None,
    ):  # 进行数据集迭代
        if change_type not in CHANGE_TYPES:
            raise ServiceError(400, f"未知的数据集迭代类型: {change_type}")
        if change_type == CHANGE_TYPE_METADATA and any(
            value is not None for value in (file_path, fields_schema, label_field)
        ):
            raise ServiceError(
                400,
                "元数据变更仅允许修改名称、摘要和详情，不能同时修改文件或字段结构",
            )
        dataset = self._get(dataset_id)
        self.db.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(dataset.logical_id)))
        )
        self.db.refresh(dataset)
        target_file_path = dataset.file_path
        target_schema = dataset.fields_schema
        target_label = dataset.label_field
        if file_path is not None:
            self._validate_file_path(file_path)
            target_file_path = canonical_dataset_path(file_path)
        if fields_schema is not None:
            target_schema = fields_schema
        if label_field is not None:
            target_label = label_field
        replace_schema = None
        if change_type == CHANGE_TYPE_REPLACE_FILE and file_path is not None:
            replace_schema = self._read_replacement_schema(
                target_file_path, target_label
            )  # 以替换文件解析出的结构为准
            target_schema = replace_schema
        if any(
            value is not None for value in (fields_schema, label_field, replace_schema)
        ):
            err = validate_fields_schema(target_schema, target_label)
            if err:
                raise ServiceError(400, err)
        target_name = name if name is not None else dataset.name
        preserve_enum_order = detect_format(target_file_path) == "arff"
        schema_unchanged = target_label == dataset.label_field and self._schema_matches(
            target_schema,
            dataset.fields_schema,
            preserve_enum_order=preserve_enum_order,
        )
        referenced = self._is_referenced(dataset.id)
        decision = resolve_iteration_policy(
            change_type, referenced=referenced, schema_unchanged=schema_unchanged
        )
        now = datetime.now(timezone.utc)
        target = dataset
        if decision.mode == MODE_IN_PLACE:
            dataset.file_path = target_file_path
            dataset.fields_schema = target_schema
            dataset.label_field = target_label
            dataset.name = target_name
            dataset.change_type = change_type
            dataset.is_breaking = decision.is_breaking
        elif decision.mode == MODE_NEW_VERSION:
            target = Dataset(
                logical_id=dataset.logical_id,
                name=target_name,
                version=self._next_version(dataset.logical_id),
                file_path=target_file_path,
                fields_schema=target_schema,
                label_field=target_label,
                uploaded_at=now,
                status=DATASET_STATUS_ACTIVE,
                change_type=change_type,
                base_version_id=dataset.id,
                is_breaking=decision.is_breaking,
            )
            self.db.add(target)
            self.db.flush()
        self._record_revision(
            dataset=dataset,
            change_type=change_type,
            decision=decision,
            summary=summary,
            detail=detail,
            result_dataset_id=None if target is dataset else target.id,
            created_at=now,
        )
        return target, decision
    def _cleanup_replaced_file(self, old_file_path: str) -> None:  # 删除不被引用的文件
        if validate_dataset_file_path(old_file_path) is not None:
            return
        try:
            referenced_paths = self.db.scalars(select(Dataset.file_path)).all()
            if any(
                path and dataset_paths_same(path, old_file_path)
                for path in referenced_paths
            ):
                return
            path = resolve_dataset_path(old_file_path)
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            logger.warning("清理被替换的数据集文件失败: %s", old_file_path)  # 删不掉记日志
        except SQLAlchemyError:
            logger.exception("检查数据集文件引用失败: %s", old_file_path)
    @service_call
    def append_rows(
        self,
        dataset_id: int,
        filename: str,
        file_bytes: bytes,
    ):
        dataset = self._get(dataset_id)
        self.db.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(dataset.logical_id)))
        )
        self.db.refresh(dataset)
        fmt = detect_format(filename)
        if fmt == "unknown":
            raise ServiceError(400, "仅支持.arff/.csv格式的增量文件")
        if detect_format(dataset.file_path) != fmt:
            raise ServiceError(400, "增量文件格式必须与当前数据集一致")
        try:
            increment_fields, increment_rows = parse_dataset_bytes(file_bytes, fmt)
        except (OSError, ValueError, csv.Error) as exc:
            raise ServiceError(400, f"增量文件解析失败: {exc}") from exc
        if not increment_rows:
            raise ServiceError(400, "增量文件没有数据行")
        increment_schema = build_fields_schema(increment_fields, dataset.label_field)
        preserve_enum_order = fmt == "arff"
        if not self._schema_matches(
            increment_schema,
            dataset.fields_schema,
            preserve_enum_order=preserve_enum_order,
        ):
            raise ServiceError(
                400,
                "增量文件字段与当前数据集不一致；"
                "如需变更字段请使用「字段变更」迭代",
            )
        previous_file_path = dataset.file_path
        current_path = resolve_dataset_path(previous_file_path)
        if not os.path.exists(current_path):
            raise ServiceError(404, f"数据集文件不存在: {current_path}")
        _, current_rows = read_all_rows(current_path)
        merged_rows = list(current_rows) + list(increment_rows)
        new_rel_path = iteration_target_path(dataset.file_path, fmt)
        added = len(increment_rows)
        try:
            write_dataset_file(
                resolve_dataset_path(new_rel_path),
                dataset.fields_schema,
                merged_rows,
                fmt,
            )
            dataset_after, decision = self._revise(
                dataset_id,
                CHANGE_TYPE_APPEND_ROWS,
                file_path=new_rel_path,
                summary=f"追加{added}条样本（{len(current_rows)} → {len(merged_rows)}）",
                detail={
                    "added_rows": added,
                    "rows_before": len(current_rows),
                    "rows_after": len(merged_rows),
                    "increment_file": filename,
                },
            )
            data = self._to_dict(dataset_after)
            if decision.mode == MODE_NEW_VERSION:
                message = f"追加样本：已新建版本v{dataset_after.version}，新增{added}条"
            else:
                message = f"追加样本：当前版本新增{added}条"
            self.commit()
        except Exception:
            self.db.rollback()
            self._cleanup_replaced_file(new_rel_path)
            raise
        # 数据库提交成功后再考虑回收旧文件
        if not dataset_paths_same(previous_file_path, new_rel_path):
            self._cleanup_replaced_file(previous_file_path)
        return ok(data=data, message=message)
    @service_call
    def get_revisions(self, dataset_id: int):
        dataset = self._get(dataset_id)
        revisions = self.db.scalars(
            select(DatasetRevision)
            .where(DatasetRevision.logical_id == dataset.logical_id)
            .order_by(DatasetRevision.created_at.desc())
        ).all()
        return ok(
            data={
                "dataset_id": dataset.id,
                "items": [revision_to_dict(revision) for revision in revisions],
            }
        )
    @service_call
    def disable(self, dataset_id: int):
        dataset = self._get(dataset_id)
        dataset.status = DATASET_STATUS_INACTIVE
        data = self._to_dict(dataset)
        self.commit()
        return ok(data=data, message="数据集已停用")
    @service_call
    def delete(self, dataset_id: int):
        dataset = self._get(dataset_id)
        if self._is_referenced(dataset_id):
            raise ServiceError(400, "数据集已被模型版本引用，只能停用")
        file_path = dataset.file_path
        self.db.delete(dataset)
        self.commit()
        self._cleanup_replaced_file(file_path)
        return ok(message='数据集已删除')
    @service_call
    def get_fields_schema(self, dataset_id: int):
        dataset = self._get(dataset_id)
        return ok(
            data={
                "dataset_id": dataset.id,
                "version": dataset.version,
                "label_field": dataset.label_field,
                "fields_schema": dataset.fields_schema,
            }
        )
    @service_call
    def get_preview(self, dataset_id: int, page: int = 1, page_size: int = 50):
        if page < 1:
            raise ServiceError(400, "页码必须大于等于1")
        if page_size < 1 or page_size > 50:
            raise ServiceError(400, "页码尺寸必须在[1,50]之间")
        dataset = self._get(dataset_id)
        path = resolve_dataset_path(dataset.file_path)
        if not os.path.exists(path):
            raise ServiceError(404, f"数据集文件不存在: {path}")
        offset = (page - 1) * page_size
        page_rows = read_sample_rows(path, dataset.fields_schema, offset, page_size)
        return ok(
            data={
                "dataset_id": dataset.id,
                "version": dataset.version,
                "label_field": dataset.label_field,
                "fields_schema": dataset.fields_schema,
                "rows": page_rows,
                "page": page,
                "page_size": page_size,
                "total": count_dataset_records(dataset.file_path),
            }
        )
