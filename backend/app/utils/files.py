"""Local file storage (design doc 3.1.3): SHA-256 fingerprint, relative-path persistence, path-traversal protection."""
import hashlib
import re
from pathlib import Path

from fastapi import HTTPException
from app.core.exceptions import AppError

from app.core.config import settings

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def validate_upload(filename: str, size: int) -> str:
    """Validate extension and size; return the lowercase extension."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise AppError("FILE_UNSUPPORTED_FORMAT", 400, f"不支持的文件格式 {ext}，仅支持 PDF / DOCX / JPG / PNG")
    if size > MAX_FILE_SIZE:
        raise AppError("FILE_TOO_LARGE", 400, "文件大小超过 50 MB 上限")
    return ext


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sanitize_filename(name: str) -> str:
    """Strip path separators and control characters to prevent forged filenames from traversing directories."""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip(" ._")
    return name[:120] or "unnamed"


def contract_dir(contract_id: int) -> Path:
    d = settings.storage_path / "contracts" / str(contract_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_origin_file(contract_id: int, version_no: int, filename: str, data: bytes) -> tuple[str, str]:
    """Save the original uploaded file; return (relative path, SHA-256)."""
    safe = sanitize_filename(filename)
    rel_dir = Path("contracts") / str(contract_id) / "origin"
    abs_dir = settings.storage_path / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    fname = f"v{version_no}_{safe}"
    (abs_dir / fname).write_bytes(data)
    rel = (rel_dir / fname).as_posix()
    return rel, sha256_bytes(data)


def resolve_storage_path(rel_path: str) -> Path:
    """Relative path -> absolute path, with path-traversal validation (after resolve it must stay inside STORAGE_ROOT)."""
    abs_path = (settings.storage_path / rel_path).resolve()
    root = settings.storage_path.resolve()
    if not abs_path.is_relative_to(root):
        raise AppError("FILE_PATH_TRAVERSAL", 403, "非法文件路径（目录穿越拦截）")
    return abs_path
