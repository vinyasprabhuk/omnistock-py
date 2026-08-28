"""
Port of src/lib/storage/StorageService.ts. Content-addressed local file
storage: uploads/<YYYY-MM-DD>/<sha256hex><ext>, UTC upload date, filename
collisions on identical bytes+extension are expected/idempotent (overwrite).
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

UPLOAD_ROOT = Path(os.environ.get("UPLOAD_DIR", str(Path(__file__).resolve().parent.parent.parent / "uploads")))


def save(file_bytes: bytes, original_name: str) -> dict:
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    directory = UPLOAD_ROOT / date_prefix
    directory.mkdir(parents=True, exist_ok=True)
    ext = Path(original_name).suffix  # includes the dot, e.g. ".pdf"; "" if none
    file_name = f"{file_hash}{ext}"
    file_path = directory / file_name
    file_path.write_bytes(file_bytes)
    return {"filePath": str(file_path), "fileHash": file_hash}


def read(file_path: str) -> bytes:
    return Path(file_path).read_bytes()
