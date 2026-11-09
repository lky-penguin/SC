"""模型版本 Service（ModelVersion）—— 本地训练任务与结果管理。

状态机：TRAINING -> FAILED / COMPLETED。训练完成后模型即可评价、导出和删除，
不包含发布、禁用或推荐状态。
"""
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select

from app.models.algorithm import Algorithm
from app.models.dataset import Dataset
from app.models.model_version import ModelVersion
from app.schemas.common import ok
from app.services.base import ServiceBase, ServiceError, service_call
from app.services.constants import (
    ALGORITHM_STATUS_AVAILABLE,
    DATASET_STATUS_ACTIVE,
    DATASET_POSITIVE_LABELS,
    MODEL_STATUS_COMPLETED,
    MODEL_STATUS_FAILED,
    MODEL_STATUS_TRAINING,
    MODEL_STATUS_TRANSITIONS,
)
from app.services.dataset_storage import resolve_dataset_path
from app.services.model_version_presenter import model_version_to_dict
from app.utils.runtime import get_logger
from app.utils.serialization import paginate
from app.utils.validation import (
    dataset_has_numeric_features,
    strip_inapplicable_params,
    validate_params_schema,
)

logger = get_logger("model_version")


class ModelVersionService(ServiceBase):
    """模型版本管理：训练启动/完成/失败、查询与删除。"""

    def _get(self, model_id: int) -> ModelVersion:
        model = self.db.get(ModelVersion, model_id)
        if model is None:
            raise ServiceError(404, "模型版本不存在")
        return model

    def _to_dict(self, model: ModelVersion, include_model_attributes: bool = False) -> dict:
        """序列化模型及训练/评估信息。"""
        return model_version_to_dict(
            model,
            include_model_attributes=include_model_attributes,
        )

    def _validate_dataset_file(self, dataset: Dataset) -> Optional[str]:
        """校验训练数据文件与注册字段结构一致（需求 3.1.1 / 3.1.2）。

        检查项（任一失败 -> 返回错误信息，禁止训练）：
        - 字段重名：实际文件出现同名两列
        - 标签字段缺失：label_field 不在实际文件中
        - 字段缺失：注册 schema 定义的字段必须全部存在于实际文件
        - 类型不匹配：注册类型（numeric/enum/string）与实际文件类型不一致
        Java/Weka 的 DataSource 同时支持 ARFF 和 CSV；CSV 使用与上传登记
        相同的字段推断逻辑，ARFF 只读头部。
        """
        from app.utils.arff_reader import read_arff
        from app.utils.dataset_file_reader import detect_format, read_csv

        path = resolve_dataset_path(dataset.file_path)
        if not os.path.exists(path):
            return f"数据集文件不存在: {path}"
        fmt = detect_format(path)
        try:
            if fmt == "arff":
                actual_fields, _ = read_arff(path, max_rows=1)
            elif fmt == "csv":
                actual_fields, _ = read_csv(path)
            else:
                return f"不支持的数据集文件格式: {fmt}，仅支持 ARFF/CSV，禁止训练"
        except Exception as exc:  # noqa: BLE001
            return f"数据集文件解析失败: {exc}"

        actual_names = [f["name"] for f in actual_fields]
        seen: set = set()
        for name in actual_names:
            if name in seen:
                return f"数据集文件字段重名: {name}，禁止训练"
            seen.add(name)

        if dataset.label_field not in actual_names:
            return f"标签字段 {dataset.label_field} 缺失，缺少标签无法监督训练，禁止训练"

        schema = dataset.fields_schema or []
        schema_names = [f["name"] for f in schema]
        missing = [name for name in schema_names if name not in actual_names]
        if missing:
            shown = "、".join(missing[:5])
            suffix = " 等" if len(missing) > 5 else ""
            return f"数据集缺少注册字段: {shown}{suffix}，禁止训练"

        actual_type = {f["name"]: f["type"] for f in actual_fields}
        for field in schema:
            expect = field.get("type")
            got = actual_type.get(field["name"])
            # 注册类型只可能取 numeric / enum / string（见 build_fields_schema）
            if expect in ("numeric", "enum", "string") and got != expect:
                return f"字段 {field['name']} 类型不匹配：注册为 {expect}，实际为 {got}，禁止训练"
        return None

    def _transition(self, model: ModelVersion, to_status: str) -> ModelVersion:
        """状态机流转。"""
        allowed = MODEL_STATUS_TRANSITIONS.get(model.status, ())
        if to_status not in allowed:
            raise ServiceError(
                400, f"模型状态不允许从 {model.status} 转换到 {to_status}"
            )
        model.status = to_status
        return model

    def _create_training_version(
        self,
        dataset_id: int,
        algorithm_id: int,
        training_parameters: Dict[str, Any],
    ) -> dict:
        """调用 create() 并恢复其被 service_call 包装后的失败状态码。"""
        created = self.create(dataset_id, algorithm_id, training_parameters)
        if created.code != 0:
            raise ServiceError(created.code, created.message)
        return created.data

    # ------------------------------------------------------------------
    # 训练（仅 ADMIN；需求 6.7.1 保存训练参数/评估指标/训练人/时间）
    # ------------------------------------------------------------------
    @service_call
    def create(
        self,
        dataset_id: int,
        algorithm_id: int,
        training_parameters: Dict[str, Any],
    ):
        """启动训练：校验数据集和算法，生成 TRAINING 状态模型版本。"""
        dataset = self.db.get(Dataset, dataset_id)
        if dataset is None:
            raise ServiceError(404, "数据集不存在")
        if dataset.status != DATASET_STATUS_ACTIVE:
            raise ServiceError(400, "数据集已停用，不能用于训练")

        algorithm = self.db.get(Algorithm, algorithm_id)
        if algorithm is None:
            raise ServiceError(404, "算法不存在")
        if algorithm.status != ALGORITHM_STATUS_AVAILABLE:
            raise ServiceError(400, "算法不可用，不能用于训练")

        if not isinstance(training_parameters, dict):
            raise ServiceError(400, "training_parameters 必须是 JSON 对象")
        # 离散化参数只在数据集含数值特征时生效（见 param_schema 的
        # requires_numeric_features）。数据集本身已是离散属性时先剔除，避免把未生效的
        # 参数写进模型记录，也避免必填校验误拦。
        has_numeric = dataset_has_numeric_features(dataset.fields_schema)
        training_parameters = strip_inapplicable_params(
            algorithm.param_schema, training_parameters, has_numeric
        )
        # 按算法注册的 param_schema 校验必填项、类型与范围（需求 6.6.3.2/6.6.3.4）。
        # 对 param_schema 为空的算法（如 PMWNB 不暴露超参数，使用服务内置默认参数），
        # 允许传入空对象 {}。
        err = validate_params_schema(algorithm.param_schema, training_parameters, has_numeric)
        if err:
            raise ServiceError(400, err)

        # 训练数据与注册字段结构一致性校验（需求 3.1.1/3.1.2）：
        # 字段缺失 / 重名 / 类型不匹配 / 标签字段缺失 -> 禁止训练。
        file_err = self._validate_dataset_file(dataset)
        if file_err:
            raise ServiceError(400, file_err)

        now = datetime.now(timezone.utc)
        model = ModelVersion(
            dataset_id=dataset_id,
            algorithm_id=algorithm_id,
            training_parameters=training_parameters,
            evaluation_metrics={},
            trained_at=now,
            status=MODEL_STATUS_TRAINING,
        )
        self.db.add(model)
        self.db.flush()
        self.commit()
        return ok(data=self._to_dict(model), message="训练启动，模型版本进入 TRAINING")

    def _run_training(self, model: ModelVersion, algorithm: Algorithm) -> None:
        metrics = self._run_algorithm_training(model, algorithm.code, model.training_parameters or {})
        self.apply_training_success(model, metrics)

    @service_call
    def train_and_save(
        self,
        dataset_id: int,
        algorithm_id: int,
        training_parameters: Dict[str, Any],
    ):
        """训练并落库（需求 6.7.1 训练执行接口，单次调用完成真实训练）。

        复用 create() 完成场景/数据集/算法/参数校验并创建 TRAINING 版本，随后：
        所有算法均调用对应 Java/Weka 真实服务，成功 -> TRAINING -> COMPLETED；
        服务异常 -> TRAINING -> FAILED。
        """
        created_data = self._create_training_version(
            dataset_id, algorithm_id, training_parameters
        )
        model = self._get(created_data["id"])
        algorithm = self.db.get(Algorithm, algorithm_id)
        try:
            self._run_training(model, algorithm)
        except Exception as exc:
            self.apply_training_failure(model, exc)
            raise ServiceError(500, f"训练失败：{exc}")
        return ok(data=self._to_dict(model), message="训练完成")

    @service_call
    def train_and_save_async(
        self,
        dataset_id: int,
        algorithm_id: int,
        training_parameters: Dict[str, Any],
    ):
        """提交异步训练：立刻返回 TRAINING 版本，真实训练在后台线程执行。

        校验、建版本、参数落库与 train_and_save 完全一致（复用
        create()），区别只是
        不在请求线程里等训练结束 —— 同步路径最长会占住一个线程池 worker 到
        TRAIN_TIMEOUT（600 秒）。

        训练结果由 training_runner 写回：成功 -> COMPLETED，失败 -> FAILED，
        字段与同步路径相同。
        """
        from app.services.training_runner import is_running, submit

        submission_error = "训练执行器未启用，无法提交后台训练"
        if not is_running():
            raise ServiceError(503, submission_error)

        created_data = self._create_training_version(
            dataset_id, algorithm_id, training_parameters
        )
        if not submit(created_data["id"]):
            # create() 已提交 TRAINING 版本；提交失败必须做补偿流转，避免留下
            # 永远不会被后台执行器推进的孤儿任务。
            model = self._get(created_data["id"])
            self.apply_training_failure(model, submission_error)
            raise ServiceError(503, submission_error)
        return ok(data=created_data, message="训练已提交，模型版本进入 TRAINING")

    def apply_training_success(self, model: ModelVersion, metrics: dict) -> None:
        """训练成功落库：TRAINING -> COMPLETED，写评估指标与模型属性。"""
        self._transition(model, MODEL_STATUS_COMPLETED)
        model.evaluation_metrics = metrics
        from app.services.model_evaluation_service import build_model_attributes
        model.model_attributes = build_model_attributes(model)
        self.commit()

    def _store_training_failure(
        self,
        model: ModelVersion,
        error_message: object | None,
        *,
        reset_metrics: bool,
    ) -> None:
        """按调用路径的既有语义保存失败状态与错误信息。"""
        self._transition(model, MODEL_STATUS_FAILED)
        if reset_metrics:
            model.evaluation_metrics = {
                "source": "error",
                "error": str(error_message),
            }
        elif error_message:
            metrics = dict(model.evaluation_metrics or {})
            metrics["error"] = str(error_message)
            model.evaluation_metrics = metrics
        self.commit()

    def apply_training_failure(self, model: ModelVersion, error: object) -> None:
        """后台/执行器失败落库：重置 metrics 并标记来源为 error。"""
        self._store_training_failure(model, error, reset_metrics=True)

    def run_training_job(self, model: ModelVersion) -> None:
        """后台执行一次训练并流转状态（供 training_runner 调用）。

        与 train_and_save 的区别只有一处：不向调用方抛异常 ——
        后台线程没有请求上下文，
        失败只能体现在模型状态上（TRAINING -> FAILED）。
        """
        model_id = model.id
        try:
            algorithm = self.db.get(Algorithm, model.algorithm_id)
            self._run_training(model, algorithm)
        except Exception as exc:  # noqa: BLE001 - 失败必须落到模型状态上
            try:
                self.apply_training_failure(model, exc)
            except Exception:  # noqa: BLE001 - 状态已无法流转（例如被人工改过）
                self.db.rollback()
                logger.exception("训练任务 #%s 标记失败时再次异常", model_id)
            else:
                logger.warning("训练任务 #%s 失败：%s", model_id, exc)

    def _run_algorithm_training(
        self, model: ModelVersion, algorithm_code: str, training_parameters: dict
    ) -> dict:
        """调用对应 Java 算法服务，并把注册 schema 校验后的参数传入 /train。"""
        from app.services.training_executor import (
            build_model_save_path,
            execute_algorithm_training,
        )

        dataset = self.db.get(Dataset, model.dataset_id)
        if dataset is None:
            raise ServiceError(404, "数据集不存在")
        dataset_path = resolve_dataset_path(dataset.file_path)
        model_save_path = build_model_save_path(model.id, algorithm_code)
        from app.services.closed_loop_data import positive_labels_for_dataset
        try:
            risk_labels = positive_labels_for_dataset(self.db, dataset)
        except Exception:
            risk_labels = sorted(DATASET_POSITIVE_LABELS.get(dataset.logical_id, set()))
        return execute_algorithm_training(
            algorithm_code,
            dataset_path,
            model_save_path,
            training_parameters,
            risk_labels,
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    @service_call
    def get_list(
        self,
        dataset_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 10,
    ):
        """模型版本列表，支持按数据集筛选。"""
        stmt = select(ModelVersion)
        if dataset_id is not None:
            stmt = stmt.where(ModelVersion.dataset_id == dataset_id)
        stmt = stmt.order_by(ModelVersion.id.desc())
        result = paginate(self.db, stmt, page, page_size)
        result["items"] = [self._to_dict(m) for m in result["items"]]
        return ok(data=result)

    @service_call
    def get(self, model_id: int):
        """模型版本详情（含评估指标）。"""
        return ok(data=self._to_dict(self._get(model_id), include_model_attributes=True))

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------
    @service_call
    def delete(self, model_id: int):
        """删除已完成或训练失败的模型版本；训练中的任务不允许删除。"""
        model = self._get(model_id)
        if model.status == MODEL_STATUS_TRAINING:
            raise ServiceError(400, "训练中的模型不能删除")
        self.db.delete(model)
        self.commit()
        return ok(message="模型版本已删除")
