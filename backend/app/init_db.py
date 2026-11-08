"""初始化软件 C 数据库、算法注册表和脱敏样例数据集。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, text, update

from app.db import Base, SessionLocal, engine
from app.models import Algorithm, Dataset, DatasetRevision, ModelVersion
from app.paths import PROJECT_ROOT
from app.services.constants import (
    ALGORITHM_CODES,
    ALGORITHM_STATUS_AVAILABLE,
    DATASET_STATUS_ACTIVE,
    MODEL_STATUS_COMPLETED,
)
from app.utils.dataset_file_reader import build_fields_schema, read_dataset_file


def _param_schema(code: str) -> list[dict]:
    if code == "PMWNB":
        return []
    schema = [
        {
            "name": "discrete_method", "label": "离散化方式", "type": "enum",
            "required": True, "default": "equal_width",
            "enum_values": ["equal_width", "equal_freq"],
            "options": [{"value": "equal_width", "label": "等宽分箱"}, {"value": "equal_freq", "label": "等频分箱"}],
            "description": "训练前对数值特征使用的 Weka 离散化方式",
        },
        {
            "name": "discrete_bins", "label": "分箱数量", "type": "int",
            "required": True, "default": 10, "min": 2, "max": 100, "step": 1,
            "description": "训练前数值特征的分箱数量",
        },
    ]
    if code == "A2WNB":
        schema.append({"name": "rode_task", "label": "RODE 权重任务", "type": "int", "required": True, "default": 1, "min": 1, "max": 4, "step": 1, "description": "RODE 内部权重评估任务"})
    if code == "CAVWNB":
        schema += [
            {"name": "objective", "label": "目标函数", "type": "enum", "required": True, "default": "CLL", "enum_values": ["CLL", "MSE"], "options": [{"value": "CLL", "label": "条件对数似然"}, {"value": "MSE", "label": "均方误差"}], "description": "CAVWNB 权重优化目标"},
            {"name": "regularizer", "label": "正则化方式", "type": "enum", "required": True, "default": "L2", "enum_values": ["None", "L2"], "options": [{"value": "None", "label": "无正则化"}, {"value": "L2", "label": "L2 正则化"}], "description": "权重优化正则化方式"},
            {"name": "regularization_lambda", "label": "正则化系数", "type": "float", "required": True, "default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1, "description": "L2 正则化系数"},
        ]
    return schema


_ALGORITHM_DISPLAY_NAMES = {
    "A2WNB": "属性增广和加权朴素贝叶斯(A2WNB)",
    "MAWNB": "多视图加权朴素贝叶斯(MAWNB)",
    "EMAWNB": "增强多视图朴素贝叶斯(EMAWNB)",
    "CAVWNB": "类依赖属性值加权朴素贝叶斯(CAVWNB)",
    "PMWNB": "矩阵视图加权朴素贝叶斯(PMWNB)",
    "DIWNB": "双视图示例加权朴素贝叶斯(DIWNB)",
    "KFDB": "K 自由依赖贝叶斯分类器(KFDB)",
    "FLNB": "基于频率的消极加权朴素贝叶斯(FLNB)",
    "FTAWNB": "基于概率微调的属性加权朴素贝叶斯(FTAWNB)",
}


def _build_algorithm_registry() -> dict[str, str]:
    """按 ALGORITHM_CODES 的稳定顺序构造注册表，并校验名称无缺漏。"""
    configured = set(_ALGORITHM_DISPLAY_NAMES)
    expected = set(ALGORITHM_CODES)
    if configured != expected:
        missing = sorted(expected - configured)
        unexpected = sorted(configured - expected)
        raise RuntimeError(
            f"算法注册名称与 ALGORITHM_CODES 不一致：missing={missing}, unexpected={unexpected}"
        )
    return {code: _ALGORITHM_DISPLAY_NAMES[code] for code in ALGORITHM_CODES}


ALGORITHMS = _build_algorithm_registry()


def relax_legacy_model_columns() -> None:
    """旧数据库保留的推荐列不再写入；放宽约束以兼容已有表。"""
    with engine.begin() as conn:
        exists = conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'model_version' AND column_name = 'is_recommended'
            )
        """)).scalar()
        if exists:
            conn.execute(text("ALTER TABLE model_version ALTER COLUMN is_recommended DROP NOT NULL"))


def normalize_model_statuses(db) -> None:
    """把旧的发布/禁用状态收敛为本地工具的“已完成”状态。"""
    db.execute(
        update(ModelVersion)
        .where(ModelVersion.status.in_(("DRAFT", "PUBLISHED", "DISABLED")))
        .values(status=MODEL_STATUS_COMPLETED)
    )
    db.commit()


def seed_algorithms(db) -> None:
    now = datetime.now(timezone.utc)
    for code, display_name in ALGORITHMS.items():
        row = db.scalar(select(Algorithm).where(Algorithm.code == code))
        if row is None:
            db.add(Algorithm(
                code=code, display_name=display_name,
                description=f"{display_name}；由原 Java/Weka 算法服务执行真实训练。",
                param_schema=_param_schema(code), status=ALGORITHM_STATUS_AVAILABLE, created_at=now,
            ))
        else:
            row.display_name = display_name
            row.param_schema = _param_schema(code)
            row.status = ALGORITHM_STATUS_AVAILABLE
    db.commit()


def seed_sample_dataset(db) -> None:
    logical_id = "sample_network_security"
    if db.scalar(select(Dataset).where(Dataset.logical_id == logical_id).limit(1)):
        return
    path = PROJECT_ROOT / "data" / "sample" / "sample_dataset.arff"
    if not path.exists():
        return
    _, fields, _ = read_dataset_file(path)
    label = "class"
    schema = build_fields_schema(fields, label)
    now = datetime.now(timezone.utc)
    row = Dataset(
        logical_id=logical_id, name="脱敏网络安全样例", version=1,
        file_path="data/sample/sample_dataset.arff", fields_schema=schema,
        label_field=label, uploaded_at=now, status=DATASET_STATUS_ACTIVE,
        change_type="create", is_breaking=False,
    )
    db.add(row)
    db.flush()
    db.add(DatasetRevision(
        logical_id=logical_id, dataset_id=row.id, change_type="create", is_breaking=False,
        mode="new_version", result_dataset_id=row.id, reason="seed sample dataset",
        summary="首次登记脱敏网络安全样例 v1", detail={"source": "data/sample/sample_dataset.arff"},
        created_at=now,
    ))
    db.commit()


def main() -> None:
    Base.metadata.create_all(bind=engine)
    relax_legacy_model_columns()
    db = SessionLocal()
    try:
        normalize_model_statuses(db)
        seed_algorithms(db)
        seed_sample_dataset(db)
        print("C database initialized: algorithms=9, sample_dataset=sample_network_security")
    finally:
        db.close()


if __name__ == "__main__":
    main()
