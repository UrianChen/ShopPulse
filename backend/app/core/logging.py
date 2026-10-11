import json
import logging
from datetime import UTC, datetime


class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Emit only explicit structured fields. Never serialize args or exc_info.
        data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", "application_event"),
        }
        for key in ("request_id", "job_id", "status", "duration_ms", "phase", "error_code"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter())
    logger = logging.getLogger("shoppulse")
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
