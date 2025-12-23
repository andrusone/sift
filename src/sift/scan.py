from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .errors import ConfigError


def scan_files(
    incoming_root: Path,
    *,
    only_ext: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> List[Path]:
    if not incoming_root.exists():
        raise ConfigError(f"paths.incoming does not exist: {incoming_root}")
    if not incoming_root.is_dir():
        raise ConfigError(f"paths.incoming is not a directory: {incoming_root}")

    exts_norm: Optional[set[str]] = None
    if only_ext:
        exts_norm = {e.lower().lstrip(".") for e in only_ext if e.strip()}

    paths = [p for p in incoming_root.rglob("*") if p.is_file()]
    paths.sort(key=lambda p: str(p.relative_to(incoming_root)))

    if exts_norm is not None:
        paths = [p for p in paths if p.suffix.lower().lstrip(".") in exts_norm]

    if limit is not None and limit >= 0:
        paths = paths[:limit]

    return paths
