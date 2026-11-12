import os
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.db import SessionLocal
from app.models.model_version import ModelVersion
from app.services.constants import MODEL_STATUS_TRAINING
from app.services.model_version_service import ModelVersionService
from app.utils.runtime import get_logger, running_under_test_runner
logger = get_logger("training_runner")
DEFAULT_WORKERS = 1
MAX_WORKERS = 4
DEFAULT_STALE_MINUTES = 60
POLL_SECONDS = 1.0
REAP_INTERVAL_SECONDS = 300.0
STOP_WAIT_SECONDS = 3.0
INTERRUPTED_ERROR = "训练任务中断，未能完成"
FAILED_ERROR = "训练执行异常，请查看后台日志"
_queue: queue.Queue[int] = queue.Queue()
_pending_ids: set[int] = set()
_stop = threading.Event()
_lock = threading.Lock()
_lifecycle_lock = threading.Lock()
_reap_lock = threading.Lock()
_threads: list[threading.Thread] = []
_started = False
def is_running() -> bool:
    with _lock:
        return _started
def submit(model_id: int) -> bool:
    model_id = int(model_id)
    with _lock:
        if not _started or _stop.is_set():
            return False
        if model_id not in _pending_ids:
            _pending_ids.add(model_id)
            _queue.put_nowait(model_id)
        return True
def _execute(model_id: int) -> None:
    with SessionLocal() as db:
        model = db.get(ModelVersion, model_id)
        if model is None:
            logger.warning("训练任务#%s对应的模型版本不存在，跳过", model_id)
            return
        if model.status != MODEL_STATUS_TRAINING:
            logger.warning("训练任务#%s状态为%s，跳过", model_id, model.status)
            return
        try:
            ModelVersionService(db).run_training_job(model)
        except Exception:
            logger.exception("训练任务#%s执行异常", model_id)
            db.rollback()
            try:
                model = db.get(ModelVersion, model_id)
                if model is not None and model.status == MODEL_STATUS_TRAINING:
                    ModelVersionService(db).apply_training_failure(model, FAILED_ERROR)
            except Exception:
                db.rollback()
                logger.exception("训练任务#%s更新失败状态时出错", model_id)
def reap_stale(stale_minutes: int | None = None) -> int:
    minutes = _stale_minutes(stale_minutes)
    if minutes <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    reaped = 0
    with _reap_lock:
        with SessionLocal() as db:
            stale_ids = db.scalars(
                select(ModelVersion.id).where(
                    ModelVersion.status == MODEL_STATUS_TRAINING,
                    ModelVersion.trained_at < cutoff,
                )
            ).all()
            service = ModelVersionService(db)
            for model_id in stale_ids:
                with _lock:   # 提交任务和标记超时互斥，防止刚入队就被清理
                    if model_id in _pending_ids:
                        continue
                    try:
                        model = db.get(ModelVersion, model_id)
                        if model is None or model.status != MODEL_STATUS_TRAINING:
                            continue
                        service.apply_training_failure(model, INTERRUPTED_ERROR)
                    except Exception:
                        db.rollback()
                        logger.exception("清理超时训练任务#%s失败", model_id)
                        continue
                reaped += 1
                logger.warning("训练任务#%s超过%s分钟未完成，已标记为FAILED", model_id, minutes)
    return reaped
def _stale_minutes(override: int | None) -> int:
    if override is not None:
        return int(override)
    try:
        return int(os.getenv("TRAINING_STALE_MINUTES", DEFAULT_STALE_MINUTES))
    except ValueError:
        return DEFAULT_STALE_MINUTES
def _worker_count(override: int | None) -> int:
    if override is None:
        try:
            override = int(os.getenv("TRAINING_RUNNER_WORKERS", DEFAULT_WORKERS))
        except ValueError:
            override = DEFAULT_WORKERS
    return min(MAX_WORKERS, max(1, int(override)))
def _reap_safely() -> None:
    try:
        reap_stale()
    except Exception:
        logger.exception("清理超时训练任务失败")
def _worker(index: int) -> None:
    if index == 0:
        _reap_safely()
    last_reap = time.monotonic()
    while not _stop.is_set():
        try:
            model_id = _queue.get(timeout=POLL_SECONDS)
        except queue.Empty:
            pass
        else:
            if _stop.is_set():
                _queue.put_nowait(model_id)
                _queue.task_done()
                break
            try:
                _execute(model_id)
            except Exception:
                logger.exception("训练任务#%s未能正常执行", model_id)
            finally:
                with _lock:
                    _pending_ids.discard(model_id)
                _queue.task_done()
        if index == 0 and time.monotonic() - last_reap >= REAP_INTERVAL_SECONDS:
            last_reap = time.monotonic()
            _reap_safely()
def start(workers: int | None = None) -> None:
    global _started
    if os.getenv("TRAINING_RUNNER_ENABLED", "1") != "1":
        logger.info("训练执行器已按TRAINING_RUNNER_ENABLED=0关闭")
        return
    if running_under_test_runner():
        return
    with _lifecycle_lock:
        with _lock:
            if _started:
                return
            if any(thread.is_alive() for thread in _threads):
                logger.warning("上一次训练执行器尚未退出，本次不重复启动")
                return
            count = _worker_count(workers)
            _stop.clear()
            _threads.clear()
            for index in range(count):
                thread = threading.Thread(
                    target=_worker,
                    args=(index,),
                    name=f"training-runner-{index}",
                    daemon=True,
                )
                thread.start()
                _threads.append(thread)
            _started = True
    logger.info("训练执行器已启动，并发数%s", count)
def stop() -> None:
    global _started
    with _lifecycle_lock:
        with _lock:
            _started = False
            _stop.set()
            threads = list(_threads)
        deadline = time.monotonic() + STOP_WAIT_SECONDS
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        with _lock:
            _threads[:] = [thread for thread in threads if thread.is_alive()]