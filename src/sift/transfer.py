from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .model import SiftConfig
from .router import route_destination


@dataclass(frozen=True)
class TransferResult:
    copied: int
    moved: int
    skipped: int
    failed: int
    details: List[Dict[str, Any]]


def _ensure_parent(dst: Path, *, mkdirs: bool) -> None:
    if mkdirs:
        dst.parent.mkdir(parents=True, exist_ok=True)


def _dedup_path(dst: Path) -> Path:
    if not dst.exists():
        return dst

    stem = dst.stem
    suffix = dst.suffix
    parent = dst.parent

    i = 1
    while True:
        cand = parent / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


def _same_file(src: Path, dst: Path) -> bool:
    try:
        return os.path.samefile(src, dst)
    except OSError:
        return False


def compute_destination(
    cfg: SiftConfig, item: Dict[str, Any]
) -> Tuple[str, str, Path, Dict[str, Any]]:
    """
    Compute final destination:

      outgoing_root/{movies|tv}/{tier.folder}/{relpath}

    Returns (media_type, tier_id, dst_path, facts)
    """
    media_type, tier, rel_dest, facts = route_destination(cfg, item)
    dst = (cfg.paths.outgoing_root / media_type / tier.folder / rel_dest).resolve()
    return media_type, tier.id, dst, facts


def transfer_inventory(
    cfg: SiftConfig,
    inventory: Dict[str, Any],
    *,
    dry_run: bool,
    only_ok_ffprobe: bool = False,
) -> TransferResult:
    items = inventory.get("items")
    if not isinstance(items, list):
        raise ValueError("inventory missing items[] list")

    copied = moved = skipped = failed = 0
    details: List[Dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        src_s = item.get("path")
        rel = item.get("relpath")
        if not isinstance(src_s, str) or not src_s:
            continue

        src = Path(src_s)

        if only_ok_ffprobe:
            ff = item.get("ffprobe")
            if not isinstance(ff, dict) or ff.get("ok") is not True:
                skipped += 1
                details.append(
                    {
                        "relpath": rel,
                        "src": str(src),
                        "action": "skip",
                        "reason": "ffprobe_not_ok",
                    }
                )
                continue

        try:
            media_type, tier_id, dst, facts = compute_destination(cfg, item)
        except Exception as e:
            failed += 1
            details.append(
                {
                    "relpath": rel,
                    "src": str(src),
                    "action": "fail",
                    "reason": f"destination_error: {e}",
                }
            )
            continue

        try:
            if not src.exists():
                skipped += 1
                details.append(
                    {
                        "relpath": rel,
                        "src": str(src),
                        "dst": str(dst),
                        "action": "skip",
                        "reason": "source_missing",
                        "media_type": media_type,
                        "tier_id": tier_id,
                        "facts": facts,
                    }
                )
                continue

            if dst.exists():
                if _same_file(src, dst):
                    skipped += 1
                    details.append(
                        {
                            "relpath": rel,
                            "src": str(src),
                            "dst": str(dst),
                            "action": "skip",
                            "reason": "already_present_samefile",
                            "media_type": media_type,
                            "tier_id": tier_id,
                            "facts": facts,
                        }
                    )
                    continue

                if cfg.io.dedupe_on_collision:
                    dst = _dedup_path(dst)
                else:
                    skipped += 1
                    details.append(
                        {
                            "relpath": rel,
                            "src": str(src),
                            "dst": str(dst),
                            "action": "skip",
                            "reason": "collision",
                            "media_type": media_type,
                            "tier_id": tier_id,
                            "facts": facts,
                        }
                    )
                    continue

            _ensure_parent(dst, mkdirs=cfg.io.mkdirs)

            if dry_run:
                details.append(
                    {
                        "relpath": rel,
                        "src": str(src),
                        "dst": str(dst),
                        "action": f"{cfg.io.mode}_dry_run",
                        "media_type": media_type,
                        "tier_id": tier_id,
                        "facts": facts,
                    }
                )
                continue

            if cfg.io.mode == "copy":
                shutil.copy2(src, dst)
                copied += 1
                details.append(
                    {
                        "relpath": rel,
                        "src": str(src),
                        "dst": str(dst),
                        "action": "copied",
                        "media_type": media_type,
                        "tier_id": tier_id,
                        "facts": facts,
                    }
                )
            elif cfg.io.mode == "move":
                shutil.move(str(src), str(dst))
                moved += 1
                details.append(
                    {
                        "relpath": rel,
                        "src": str(src),
                        "dst": str(dst),
                        "action": "moved",
                        "media_type": media_type,
                        "tier_id": tier_id,
                        "facts": facts,
                    }
                )
            else:
                failed += 1
                details.append(
                    {
                        "relpath": rel,
                        "src": str(src),
                        "dst": str(dst),
                        "action": "fail",
                        "reason": f"unknown_mode: {cfg.io.mode}",
                    }
                )

        except Exception as e:
            failed += 1
            details.append(
                {
                    "relpath": rel,
                    "src": str(src),
                    "dst": str(dst),
                    "action": "fail",
                    "reason": f"exception: {type(e).__name__}: {e}",
                    "media_type": media_type,
                    "tier_id": tier_id,
                    "facts": facts,
                }
            )

    return TransferResult(
        copied=copied, moved=moved, skipped=skipped, failed=failed, details=details
    )
