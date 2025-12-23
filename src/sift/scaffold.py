from __future__ import annotations

from pathlib import Path
from typing import List

from .model import SiftConfig


def ensure_dirs(cfg: SiftConfig) -> List[Path]:
    ensured: List[Path] = []

    def _mk(p: Path) -> None:
        p.mkdir(parents=True, exist_ok=True)
        ensured.append(p)

    _mk(cfg.paths.outgoing_root)
    _mk(cfg.paths.metadata_cache)

    if cfg.reporting.write_jsonl_report:
        _mk(cfg.reporting.report_path.parent)

    for media_type in ("movies", "tv"):
        base = cfg.paths.outgoing_root / media_type
        _mk(base)
        for t in cfg.tier_model.tier:
            _mk(base / t.folder)

    return ensured


def planned_folders(cfg: SiftConfig) -> List[Path]:
    folders: List[Path] = [cfg.paths.outgoing_root, cfg.paths.metadata_cache]
    if cfg.reporting.write_jsonl_report:
        folders.append(cfg.reporting.report_path.parent)

    for media_type in ("movies", "tv"):
        base = cfg.paths.outgoing_root / media_type
        folders.append(base)
        for t in cfg.tier_model.tier:
            folders.append(base / t.folder)

    return sorted(set(folders), key=lambda p: str(p))
