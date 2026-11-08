"""数据集文件的路径安全、上传落盘、格式识别与记录数统计。"""
from __future__ import annotations

import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.paths import PROJECT_ROOT
from app.utils.arff_reader import count_arff_rows
from app.utils.dataset_file_reader import count_csv_rows, detect_format
from app.utils.runtime import get_logger

logger = get_logger("dataset_storage")
SUPPORTED_DATA_FORMATS = frozenset({"arff", "csv", "json"})


def normalize_dataset_path(file_path: str) -> str:
    """统一使用正斜杠，兼容历史 Windows 路径。"""
    return str(file_path).replace("\\", "/")


def validate_dataset_file_path(file_path: str) -> str | None:
    """校验登记路径必须是 data/ 下的相对路径。"""
    if not file_path:
        return "file_path 必须是 data/ 目录下的相对路径"
    normalized = normalize_dataset_path(file_path)
    candidate = Path(normalized)
    if candidate.is_absolute():
        return "file_path 必须是 data/ 目录下的相对路径"
    if ".." in candidate.parts or candidate.parts[:1] != ("data",):
        return "file_path 必须位于 data/ 目录内"
    return None


def canonical_dataset_path(file_path: str) -> str:
    """返回可持久化的 data-relative POSIX 路径。

    仅对已通过 data/ 安全校验的登记路径做点段与分隔符规范化；历史绝对路径
    原样返回，避免绕过既有安全边界。
    """
    normalized = normalize_dataset_path(file_path)
    if validate_dataset_file_path(normalized) is not None:
        return normalized
    return Path(os.path.normpath(normalized)).as_posix()


def resolve_dataset_path(file_path: str) -> str:
    """把 dataset.file_path 解析为绝对路径。"""
    normalized = normalize_dataset_path(file_path)
    if os.path.isabs(normalized):
        return normalized
    return str(PROJECT_ROOT / normalized)


def _path_identity(file_path: str) -> str:
    resolved = os.path.realpath(resolve_dataset_path(file_path))
    return os.path.normcase(os.path.abspath(os.path.normpath(resolved)))


def dataset_paths_same(left: str, right: str) -> bool:
    return _path_identity(left) == _path_identity(right)


def dataset_format(file_path: str) -> str:
    """返回展示/处理用的数据集格式。"""
    suffix = Path(normalize_dataset_path(file_path)).suffix.lstrip(".").lower()
    return suffix if suffix in SUPPORTED_DATA_FORMATS else "arff"


def safe_upload_filename(filename: str) -> str:
    """从上传文件名中剥离路径，阻止目录穿越。"""
    safe_name = os.path.basename(normalize_dataset_path(filename)).strip()
    if not safe_name or safe_name in (".", ".."):
        raise ValueError("文件名不合法")
    return safe_name


def _claim_unique_upload_path(target_root: Path, safe_name: str) -> Path:
    """原子占用一个此前不存在的上传路径，绝不覆盖已有文件。"""
    safe_path = Path(safe_name)
    stem = safe_path.stem
    suffix = safe_path.suffix
    candidate = target_root / safe_name

    for _ in range(100):
        try:
            descriptor = os.open(
                candidate,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            candidate = target_root / f"{stem}__{uuid.uuid4().hex}{suffix}"
            continue
        os.close(descriptor)
        return candidate
    raise OSError("无法生成唯一的上传文件路径")


def save_uploaded_dataset(
    filename: str,
    file_bytes: bytes,
    *,
    upload_root: Path | None = None,
    project_root: Path = PROJECT_ROOT,
) -> str:
    """原子保存上传文件并返回登记路径；同名文件自动生成唯一名称。"""
    safe_name = safe_upload_filename(filename)
    safe_path = Path(safe_name)
    target_root = upload_root or (project_root / "data" / "uploads")
    target_root.mkdir(parents=True, exist_ok=True)

    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{safe_path.stem}__",
        suffix=f"{safe_path.suffix}.tmp",
        dir=target_root,
    )
    temp_path = Path(temp_name)
    claimed_target: Path | None = None
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(file_bytes)
            handle.flush()
            os.fsync(handle.fileno())

        claimed_target = _claim_unique_upload_path(target_root, safe_name)
        os.replace(temp_path, claimed_target)
    except Exception:
        if claimed_target is not None:
            claimed_target.unlink(missing_ok=True)
        raise
    finally:
        temp_path.unlink(missing_ok=True)

    try:
        return claimed_target.relative_to(project_root).as_posix()
    except ValueError:
        return claimed_target.as_posix()


def iteration_target_path(
    file_path: str,
    fmt: str,
    *,
    now: datetime | None = None,
) -> str:
    """为一次带文件的数据集迭代生成唯一物理路径。"""
    normalized = normalize_dataset_path(file_path)
    parent = str(Path(normalized).parent).replace("\\", "/")
    stem = Path(normalized).stem
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d%H%M%S%f")
    return f"{parent}/{stem}__rev{stamp}.{fmt}"


class DatasetRecordCounter:
    """按文件 mtime/size 缓存记录数，避免列表刷新时反复扫盘。"""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[int, int, int]] = {}
        self._lock = threading.Lock()

    def count(self, file_path: str) -> int:
        try:
            path = resolve_dataset_path(file_path)
            if not os.path.exists(path):
                return 0
            stat = os.stat(path)
            signature = (stat.st_mtime_ns, stat.st_size)
            with self._lock:
                cached = self._cache.get(path)
            if cached and cached[:2] == signature:
                return cached[2]

            if detect_format(path) == "csv":
                total = count_csv_rows(path)
            else:
                total = count_arff_rows(path)
            with self._lock:
                self._cache[path] = (*signature, total)
            return total
        except Exception:  # noqa: BLE001 - 列表接口不应因单个损坏文件整体失败
            logger.exception("统计数据集样本数失败: %s", file_path)
            return 0


record_counter = DatasetRecordCounter()


def count_dataset_records(file_path: str) -> int:
    """统计 ARFF/CSV 数据集的数据行数。"""
    return record_counter.count(file_path)
