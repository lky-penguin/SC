"""数据集版本、迭代与文件生命周期。

dataset 行表示一个版本；每次变更都写 DatasetRevision，是否新建版本由
resolve_iteration_policy 决定，原地更新同样保留审计记录。
"""
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from sqlalchemy import func, select

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
    CHANGE_TYPE_SCHEMA_CHANGE,
    CHANGE_TYPES,
    MODE_IN_PLACE,
    MODE_NEW_VERSION,
    change_type_label,
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
    """数据集管理（上传/版本/停用/删除）+ 字段结构校验。"""

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
    def _require_supported_upload(filename: str, message: str) -> str:
        fmt = detect_format(filename)
        if fmt == "unknown":
            raise ServiceError(400, message)
        return fmt

    @staticmethod
    def _parse_uploaded_dataset(parser, error_message: str, *args):
        try:
            return parser(*args)
        except Exception as exc:  # noqa: BLE001
            raise ServiceError(400, f"{error_message}: {exc}") from exc

    @staticmethod
    def _schema_from_uploaded_fields(
        fields: List[Dict], label_field: str, *, subject: str, missing_suffix: str = ""
    ) -> List[Dict]:
        if not fields:
            raise ServiceError(400, f"{subject}没有解析出任何字段")
        names = [str(field.get("name", "")) for field in fields]
        if label_field not in names:
            raise ServiceError(
                400,
                f"标签字段 {label_field} 不存在于{subject}字段中（可用字段: {', '.join(names[:10])}{missing_suffix}）",
            )
        return build_fields_schema(fields, label_field)

    @staticmethod
    def _schema_structure(
        schema: Optional[List[Dict]],
        *,
        preserve_enum_order: bool = True,
    ) -> tuple:
        """提取影响兼容性的字段结构；样例值变化不算破坏性结构变更。

        ARFF nominal 的声明顺序（尤其 label/arff_values）有语义，默认按原序列
        比较。CSV 没有显式值域声明，解析器会稳定排序推断值域；仅该格式替换
        比较时允许按排序后的值域判断兼容性。
        """
        return tuple(
            (
                str(field.get("name", "")),
                str(field.get("role", "feature")),
                str(field.get("type", "")),
                (
                    tuple(str(value) for value in (field.get("enum_values") or []))
                    if preserve_enum_order
                    else tuple(
                        sorted(
                            str(value)
                            for value in (field.get("enum_values") or [])
                        )
                    )
                ),
            )
            for field in (schema or [])
            if isinstance(field, dict)
        )

    def _read_replacement_schema(
        self, file_path: str, label_field: str
    ) -> List[Dict]:
        """读取替换文件的实际 ARFF/CSV 字段，并构造成可入库字段结构。"""
        fields = self._parse_uploaded_dataset(
            read_dataset_fields, "替换文件解析失败", resolve_dataset_path(file_path)
        )
        return self._schema_from_uploaded_fields(
            fields, label_field, subject="替换文件"
        )

    @staticmethod
    def _cleanup_unregistered_upload(file_path: str) -> None:
        """清理未能登记成功的新上传文件；仅允许触碰 data/ 下路径。"""
        if validate_dataset_file_path(file_path) is not None:
            return
        try:
            path = resolve_dataset_path(file_path)
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            logger.warning("清理未登记的上传文件失败: %s", file_path)

    @staticmethod
    def _dataset_metadata(dataset: Dataset) -> dict:
        return {
            "dataset_id": dataset.id,
            "version": dataset.version,
            "label_field": dataset.label_field,
            "fields_schema": dataset.fields_schema,
        }

    def _next_version(self, logical_id: str) -> int:
        max_version = self.db.scalar(
            select(func.max(Dataset.version)).where(Dataset.logical_id == logical_id)
        ) or 0
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
        is_breaking: bool,
        mode: str,
        reason: str,
        summary: Optional[str],
        detail: Optional[Dict],
        result_dataset_id: Optional[int],
        created_at: datetime,
    ) -> None:
        """写一条迭代记录（原地更新也留痕，保证「迭代 = 全部记录」）。

        dataset_id 指向被迭代的目标版本行；result_dataset_id
        仅在新建版本时给出。
        """
        self.db.add(
            DatasetRevision(
                logical_id=dataset.logical_id,
                dataset_id=dataset.id,
                change_type=change_type,
                is_breaking=is_breaking,
                mode=mode,
                result_dataset_id=result_dataset_id,
                reason=reason,
                summary=summary,
                detail=detail,
                created_at=created_at,
            )
        )

    def _to_dict(self, dataset: Dataset) -> dict:
        """序列化数据集，并补充前端列表/详情常用展示字段。"""
        return dataset_to_dict(
            dataset,
            record_count=count_dataset_records(dataset.file_path),
            referenced=self._is_referenced(dataset.id),
        )

    # ------------------------------------------------------------------
    # 查询（需求 2.3.1 / 6.5.2：查看列表与字段预览 -> 允许/允许）
    # ------------------------------------------------------------------
    @service_call
    def get_list(
        self,
        page: int = 1,
        page_size: int = 10,
    ):
        """个人版数据集列表。"""
        stmt = select(Dataset).order_by(Dataset.logical_id, Dataset.version)
        result = paginate(self.db, stmt, page, page_size)
        result["items"] = [self._to_dict(d) for d in result["items"]]
        return ok(data=result)

    @service_call
    def get(self, dataset_id: int):
        """数据集详情（含字段结构 fields_schema）。"""
        return ok(data=self._to_dict(self._get(dataset_id)))

    @service_call
    def get_versions(self, dataset_id: int):
        """返回同一数据集的全部版本。"""
        dataset = self._get(dataset_id)
        versions = self.db.scalars(
            select(Dataset)
            .where(Dataset.logical_id == dataset.logical_id)
            .order_by(Dataset.version.desc())
        ).all()
        return ok(data={"items": [self._to_dict(item) for item in versions]})

    # ------------------------------------------------------------------
    # 上传 / 版本 / 停用 / 删除（数据级别由上传者角色决定，创建后不可变）
    # ------------------------------------------------------------------
    @staticmethod
    def _generated_logical_id() -> str:
        """生成仅供系统内部使用的稳定数据集标识。"""
        return f"ds_{uuid4().hex}"

    @staticmethod
    def _default_label_field(fields_schema: List[Dict]) -> str:
        """未指定时，将最后一列识别为标签字段。"""
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
        fields_schema: List[Dict],
        label_field: Optional[str] = None,
        logical_id: Optional[str] = None,
    ):
        """登记数据集；内部标识由系统生成，版本号自动取最大值 + 1。"""
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

        # 初次登记也走同一套策略：change_type=create -> 直接生成首个版本
        decision = resolve_iteration_policy(CHANGE_TYPE_CREATE, referenced=False)

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
            is_breaking=decision.is_breaking,
            mode=decision.mode,
            reason=decision.reason,
            summary=f"登记数据集 {name} v{dataset.version}",
            detail=None,
            result_dataset_id=dataset.id,
            created_at=now,
        )
        self.commit()
        return ok(data=self._to_dict(dataset), message="数据集上传成功")

    @service_call
    def upload_from_file(
        self,
        name: str,
        filename: str,
        file_bytes: bytes,
    ):
        """上传数据集文件；名称由用户填写，标签字段自动取最后一列。"""
        fmt = self._require_supported_upload(filename, "仅支持 .arff / .csv 格式文件")

        try:
            relative_path = save_uploaded_dataset(filename, file_bytes)
        except ValueError as exc:
            raise ServiceError(400, str(exc)) from exc

        try:
            saved_path = resolve_dataset_path(relative_path)
            fields = self._parse_uploaded_dataset(
                read_dataset_fields, "文件解析失败", saved_path
            )
            label_field = self._default_label_field(fields)
            fields_schema = self._schema_from_uploaded_fields(
                fields, label_field, subject="文件", missing_suffix="..."
            )
            response = self.create(
                name=name,
                file_path=relative_path,
                fields_schema=fields_schema,
                label_field=label_field,
            )
        except Exception:
            self._cleanup_unregistered_upload(relative_path)
            raise

        if response.code != 0:
            self._cleanup_unregistered_upload(relative_path)
        return response

    @service_call
    def revise(
        self,
        dataset_id: int,
        change_type: str,
        file_path: Optional[str] = None,
        fields_schema: Optional[List[Dict]] = None,
        label_field: Optional[str] = None,
        name: Optional[str] = None,
        summary: Optional[str] = None,
        detail: Optional[Dict] = None,
    ):
        """数据集迭代统一入口（管理级角色，场景管理员仅自己场景）。

        change_type 取 dataset_iteration.CHANGE_TYPES；是否新开版本由策略决定：
        破坏结构兼容（字段/标签变更）必然新建版本；兼容迭代（追加/修正样本）在
        已被模型引用时新建版本，未被引用时原地更新当前版本行（版本号不变）。
        """
        dataset, decision = self._revise(
            dataset_id,
            change_type,
            file_path=file_path,
            fields_schema=fields_schema,
            label_field=label_field,
            name=name,
            summary=summary,
            detail=detail,
        )
        label = change_type_label(change_type)
        if decision.mode == MODE_NEW_VERSION:
            message = f"{label}：已新建版本 v{dataset.version}（旧版本保留）"
        else:
            message = f"{label}：已原地更新当前版本"
        return ok(data=self._to_dict(dataset), message=message)

    @service_call
    def update(
        self,
        dataset_id: int,
        file_path: Optional[str] = None,
        fields_schema: Optional[List[Dict]] = None,
        label_field: Optional[str] = None,
    ):
        """旧接口（PUT /datasets/{id}）：等价于一次「字段变更 / 文件替换」迭代。

        保留给已有前端调用方；内部统一走 _revise，不再单独维护一套版本逻辑。
        """
        change_type = (
            CHANGE_TYPE_SCHEMA_CHANGE
            if (fields_schema is not None or label_field is not None)
            else CHANGE_TYPE_REPLACE_FILE
        )
        dataset, decision = self._revise(
            dataset_id,
            change_type,
            file_path=file_path,
            fields_schema=fields_schema,
            label_field=label_field,
        )
        if decision.mode == MODE_NEW_VERSION:
            message = "原数据集已被模型引用，已创建新版本（旧版本保留）"
        else:
            message = "数据集修改成功"
        return ok(data=self._to_dict(dataset), message=message)

    def _revise(
        self,
        dataset_id: int,
        change_type: str,
        *,
        file_path: Optional[str] = None,
        fields_schema: Optional[List[Dict]] = None,
        label_field: Optional[str] = None,
        name: Optional[str] = None,
        summary: Optional[str] = None,
        detail: Optional[Dict] = None,
    ):
        """执行一次迭代，返回 (目标版本行, 决策)。

        策略见 dataset_iteration.resolve_iteration_policy：
        - 破坏结构兼容 -> 必新建版本（即使未被引用也留痕）；
        - 兼容 + 已被引用 -> 新建版本，冻结旧文件；
        - 兼容 + 未被引用 -> 原地更新当前版本行（不涨版本号，仍记迭代记录）。
        """
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

        previous_file_path = dataset.file_path

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
            # 整包替换必须相信文件实际结构，而不是调用方是否传了 fields_schema。
            replace_schema = self._read_replacement_schema(
                target_file_path, target_label
            )
            target_schema = replace_schema

        if (
            fields_schema is not None
            or label_field is not None
            or replace_schema is not None
        ):
            err = validate_fields_schema(target_schema, target_label)
            if err:
                raise ServiceError(400, err)

        target_name = name if name is not None else dataset.name

        if replace_schema is not None:
            preserve_enum_order = detect_format(target_file_path) == "arff"
            schema_unchanged = (
                self._schema_structure(
                    replace_schema,
                    preserve_enum_order=preserve_enum_order,
                )
                == self._schema_structure(
                    dataset.fields_schema,
                    preserve_enum_order=preserve_enum_order,
                )
                and target_label == dataset.label_field
            )
        else:
            schema_unchanged = (
                list(target_schema) == list(dataset.fields_schema)
                and target_label == dataset.label_field
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
        else:
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
            is_breaking=decision.is_breaking,
            mode=decision.mode,
            reason=decision.reason,
            summary=summary,
            detail=detail,
            result_dataset_id=None if target is dataset else target.id,
            created_at=now,
        )
        self.commit()
        if not dataset_paths_same(previous_file_path, target_file_path):
            self._cleanup_replaced_file(
                previous_file_path, replacement_file_path=target_file_path
            )
        return target, decision

    def _cleanup_replaced_file(
        self,
        old_file_path: str,
        *,
        replacement_file_path: str | None = None,
    ) -> None:
        """迭代换文件后清理不再被任何版本引用的旧物理文件（best-effort）。

        只在没有任何 dataset 行仍指向它时删除：
        只改字段的旧路径可能被多个版本共用，
        贸然删除会让历史版本读不到文件。删除失败只记日志，不影响迭代结果。
        """
        if not old_file_path:
            return
        if validate_dataset_file_path(old_file_path) is not None:
            return
        if (
            replacement_file_path is not None
            and dataset_paths_same(old_file_path, replacement_file_path)
        ):
            return

        scalars = getattr(self.db, "scalars", None)
        if callable(scalars):
            referenced_paths = scalars(select(Dataset.file_path)).all()
            if any(
                path and dataset_paths_same(path, old_file_path)
                for path in referenced_paths
            ):
                return
        else:
            # 兼容只实现最小 Session 协议的测试替身/旧适配层。
            still_used = self.db.scalar(
                select(func.count())
                .select_from(Dataset)
                .where(Dataset.file_path == old_file_path)
            )
            if still_used:
                return

        try:
            path = resolve_dataset_path(old_file_path)
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            logger.warning("清理被替换的数据集文件失败: %s", old_file_path)

    @service_call
    def append_rows(
        self,
        dataset_id: int,
        filename: str,
        file_bytes: bytes,
    ):
        """追加样本（管理级角色，场景管理员仅自己场景）。

        把「增量文件」并入当前数据集：增量必须是同结构（字段名同名同序）的
        ARFF / CSV。合并后写到新物理文件，再交给 _revise 按迭代策略决定
        原地更新还是新建版本 —— 未被引用时版本号不变（只增数据），已被引用时
        自动新开版本冻结旧文件。

        需要改变字段结构请改用「字段变更」迭代，本方法只负责增加数据条数。
        """
        dataset = self._get(dataset_id)

        fmt = self._require_supported_upload(
            filename, "仅支持 .arff / .csv 格式的增量文件"
        )
        if detect_format(dataset.file_path) != fmt:
            raise ServiceError(400, "增量文件格式必须与当前数据集一致")

        increment_fields, increment_rows = self._parse_uploaded_dataset(
            parse_dataset_bytes, "增量文件解析失败", file_bytes, fmt
        )
        if not increment_rows:
            raise ServiceError(400, "增量文件没有数据行")

        expected_names = [str(f.get("name")) for f in (dataset.fields_schema or [])]
        actual_names = [str(f.get("name")) for f in increment_fields]
        if actual_names != expected_names:
            raise ServiceError(
                400,
                "增量文件字段与当前数据集不一致（追加要求同名同序）；"
                "如需变更字段请使用「字段变更」迭代",
            )

        current_path = resolve_dataset_path(dataset.file_path)
        if not os.path.exists(current_path):
            raise ServiceError(404, f"数据集文件不存在: {current_path}")
        _, current_rows = read_all_rows(current_path)
        merged_rows = list(current_rows) + list(increment_rows)

        new_rel_path = iteration_target_path(dataset.file_path, fmt)
        write_dataset_file(
            resolve_dataset_path(new_rel_path), dataset.fields_schema, merged_rows, fmt
        )

        added = len(increment_rows)
        dataset_after, decision = self._revise(
            dataset_id,
            CHANGE_TYPE_APPEND_ROWS,
            file_path=new_rel_path,
            summary=f"追加 {added} 条样本（{len(current_rows)} → {len(merged_rows)}）",
            detail={
                "added_rows": added,
                "rows_before": len(current_rows),
                "rows_after": len(merged_rows),
                "increment_file": filename,
            },
        )
        if decision.mode == MODE_NEW_VERSION:
            message = f"追加样本：已新建版本 v{dataset_after.version}，新增 {added} 条"
        else:
            message = f"追加样本：当前版本新增 {added} 条（版本号不变）"
        return ok(data=self._to_dict(dataset_after), message=message)

    @service_call
    def get_revisions(self, dataset_id: int):
        """迭代历史：每次迭代一条，含原地更新。"""
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
        """停用数据集；历史模型、训练记录和评估结果保持可追溯。"""
        dataset = self._get(dataset_id)
        dataset.status = DATASET_STATUS_INACTIVE
        self.commit()
        return ok(data=self._to_dict(dataset), message="数据集已停用")

    @service_call
    def delete(self, dataset_id: int):
        """物理删除数据集；被模型版本引用时只能停用。"""
        dataset = self._get(dataset_id)
        if self._is_referenced(dataset_id):
            raise ServiceError(400, "数据集已被模型版本引用，禁止物理删除，只能停用")
        self.db.delete(dataset)
        self.commit()
        return ok(message="数据集已删除")

    @service_call
    def get_fields_schema(self, dataset_id: int):
        """字段预览：字段名、类型、角色和样例值。"""
        dataset = self._get(dataset_id)
        return ok(data=self._dataset_metadata(dataset))

    @service_call
    def get_preview(
        self,
        dataset_id: int,
        page: int = 1,
        page_size: int = 50,
    ):
        """数据内容预览（需求 2.4：前 N 条数据、标签列高亮、分页）。

        - 性能：单次最多返回 50 条，后端从数据文件直接读取。
        """
        if page_size > 50:
            page_size = 50
        dataset = self._get(dataset_id)

        path = resolve_dataset_path(dataset.file_path)
        if not os.path.exists(path):
            raise ServiceError(404, f"数据集文件不存在: {path}")

        offset = (page - 1) * page_size
        # 取样本的统一入口（ARFF / CSV 都支持，字段名取登记的 fields_schema），
        # 与「批量研判」共用，避免两处口径漂移。
        page_rows = read_sample_rows(path, dataset.fields_schema, offset, page_size)
        total = count_dataset_records(dataset.file_path)
        data = self._dataset_metadata(dataset)
        data.update(
            {
                "rows": page_rows,
                "page": page,
                "page_size": len(page_rows),
                "total": total,
            }
        )
        return ok(data=data)
