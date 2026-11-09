"""Java 算法客户端共用的运行期配置。"""

import os

from app.paths import MODEL_STORAGE_ROOT
from app.services.constants import ALGORITHM_CODES


PMWNB_SERVICE_URL = os.getenv("PMWNB_SERVICE_URL", "http://127.0.0.1:18211")
TRAIN_TIMEOUT = int(os.getenv("NB_TRAIN_TIMEOUT", "600"))
PREDICT_TIMEOUT = int(os.getenv("NB_PREDICT_TIMEOUT", "60"))
# 8 个 NB 算法共用同一个服务进程：jar 字节完全相同，算法由请求体的 algorithm_code 指定。
# 单算法独立部署时可用 <算法名>_SERVICE_URL 覆盖其中一路。
NB_ALGORITHM_SERVICE_URL = os.getenv("NB_ALGORITHM_SERVICE_URL", "http://127.0.0.1:18212")
ALGORITHM_SERVICE_URLS = {
    code: os.getenv(f"{code}_SERVICE_URL", NB_ALGORITHM_SERVICE_URL)
    for code in ALGORITHM_CODES
    if code != "PMWNB"
}

TRAINED_MODEL_DIR = str(MODEL_STORAGE_ROOT)

