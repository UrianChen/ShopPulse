import json
import os
import uuid
from pathlib import Path

from app.core.config import settings


def storage_root() -> Path:
    root = settings().path(settings().storage_root).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def object_path(key: str) -> Path:
    root = storage_root()
    path = (root / key).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Invalid storage object")
    return path


def write_json(key: str, value: dict):
    path = object_path(key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(key: str):
    return json.loads(object_path(key).read_text(encoding="utf-8"))
