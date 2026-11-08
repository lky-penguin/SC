"""个人数据集训练系统使用的稳定业务常量。"""
DATASET_STATUS_ACTIVE = "ACTIVE"
DATASET_STATUS_INACTIVE = "INACTIVE"
DATASET_LOGICAL_ID_MAX_LEN = 64
DATASET_FILE_PATH_MAX_LEN = 255
DATASET_LABEL_FIELD_MAX_LEN = 64

ALGORITHM_STATUS_AVAILABLE = "AVAILABLE"
ALGORITHM_CODES = (
    "A2WNB", "MAWNB", "EMAWNB", "CAVWNB", "PMWNB", "DIWNB",
    "KFDB", "FLNB", "FTAWNB",
)

MODEL_STATUS_TRAINING = "TRAINING"
MODEL_STATUS_FAILED = "FAILED"
MODEL_STATUS_COMPLETED = "COMPLETED"
MODEL_STATUS_TRANSITIONS = {
    MODEL_STATUS_TRAINING: (MODEL_STATUS_FAILED, MODEL_STATUS_COMPLETED),
    MODEL_STATUS_FAILED: (),
    MODEL_STATUS_COMPLETED: (),
}

DATASET_POSITIVE_LABELS = {
    "sample_network_security": {"anomaly"},
    "kdd_train_20": {"anomaly"},
    "nf_unsw_nb15": {"1"},
    "powergrid_knowledge": {"1"},
    "dis_raw_data": {"1"},
    "dis_landslides": {"1"},
    "dis_causative_factors": {"1"},
    "dis_guaruja_random": {"1"},
    "carrier_feature2_biaoqian": {"1"},
    "carrier_feature2_lisan": {"1"},
    "carrier_paired_trail": {"1"},
}


def dataset_display_name_of(dataset: object | None) -> str | None:
    if dataset is None:
        return None
    return getattr(dataset, "name", None) or getattr(dataset, "logical_id", None)
