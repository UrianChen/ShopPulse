import argparse
import logging
import signal
import threading
import time

from app.core.config import settings
from app.core.logging import configure_logging
from app.jobs.queue import claim, finish, heartbeat

logger = logging.getLogger("shoppulse")
stopping = threading.Event()
SCHEDULER_INTERVAL = 30
MAINTENANCE_INTERVAL = 600


def run_one() -> bool:
    job = claim()
    if not job:
        return False
    from app.ops.jobs import pulse

    pulse(job.id)
    done = threading.Event()

    def renew():
        while not done.wait(settings().job_heartbeat_seconds):
            try:
                pulse(job.id)
                if not heartbeat(job):
                    return
            except Exception:
                logger.warning("heartbeat_failed", extra={"event": "heartbeat_failed"})
                return

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        if job.type in {"parse_upload", "validate_import", "publish_dataset"}:
            from app.ingestion.service import execute

            execute(job)
        elif job.type == "build_metrics":
            from app.metrics.service import execute as execute_metrics

            execute_metrics(job)
        elif job.type in {"build_report", "report_question"}:
            from app.reports.service import execute as execute_report

            execute_report(job)
        elif job.type == "test_model":
            from app.providers.service import execute as execute_model

            execute_model(job)
        elif job.type == "export_report":
            from app.exports.service import execute as execute_export

            execute_export(job)
        elif job.type == "notify_webhook":
            from app.automation.notify import execute as execute_notify

            execute_notify(job)
        else:
            finish(job, error_code="UNKNOWN_JOB_TYPE")
    except Exception:
        # A DB outage leaves the lease to expire; no false successful acknowledgement.
        try:
            if job.type in {"parse_upload", "validate_import", "publish_dataset"}:
                from app.ingestion.service import commit_result

                commit_result(job, {"error": "处理失败，请检查文件与配置后重试。"})
            elif job.type in {"build_report", "report_question"}:
                from app.reports.service import fail_job

                fail_job(job)
            else:
                finish(job, error_code="EXECUTION_FAILED")
                from sqlalchemy.orm import Session

                from app.db import session as db_module
                from app.db.models import Job
                from app.ops.jobs import settle

                with Session(db_module.engine()) as db, db.begin():
                    current = db.get(Job, job.id)
                    if current and current.status == "failed":
                        settle(db, current, "EXECUTION_FAILED")
        except Exception:
            pass
        logger.error("job_failed", extra={"event": "job_failed", "job_id": str(job.id)})
    finally:
        done.set()
        thread.join(timeout=2)
        try:
            pulse()
        except Exception:
            pass
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Execute at most one job, then exit")
    args = parser.parse_args()
    settings().validate_secrets()
    configure_logging(settings().log_level)
    from app.observability.tracing import init as init_tracing

    init_tracing("shoppulse-worker")
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    logger.info("worker_started", extra={"event": "worker_started"})
    last_tick = last_maintenance = 0.0
    while not stopping.is_set():
        try:
            from app.ops.jobs import pulse

            pulse()
            if time.monotonic() - last_maintenance >= MAINTENANCE_INTERVAL:
                last_maintenance = time.monotonic()
                from app.observability.retention import purge_debug

                purge_debug()
            if time.monotonic() - last_tick >= SCHEDULER_INTERVAL:
                last_tick = time.monotonic()
                from app.automation.scheduler import tick

                try:
                    tick()
                except Exception:
                    logger.error("scheduler_failed", extra={"event": "scheduler_failed"})
            worked = run_one()
        except Exception:
            logger.error("worker_dependency_error", extra={"event": "worker_dependency_error"})
            if args.once:
                raise SystemExit(1) from None
            worked = False
        if args.once:
            break
        if not worked:
            stopping.wait(settings().job_poll_seconds)


if __name__ == "__main__":
    main()
