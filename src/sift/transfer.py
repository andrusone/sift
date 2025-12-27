from __future__ import annotations

import os
import re
import shutil
import time
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


def _copy_with_progress(src: Path, dst: Path, *, chunk_size: int = 1024 * 1024) -> None:
    """Copy file in chunks and print progress (percentage, MB/s, ETA).

    Raises any exception encountered; preserves file metadata with copystat on success.
    """
    total = src.stat().st_size
    copied = 0
    start = time.monotonic()
    last_print_pct = -1

    # Ensure parent dir exists for the destination (caller should have created it already)
    with src.open("rb") as inf, dst.open("wb") as outf:
        while True:
            chunk = inf.read(chunk_size)
            if not chunk:
                break
            outf.write(chunk)
            copied += len(chunk)

            # Print every 10% boundary or at completion
            if total > 0:
                pct = int(copied * 100 / total)
            else:
                pct = 100

            if pct != last_print_pct and (pct % 10 == 0 or pct == 100):
                elapsed = time.monotonic() - start
                rate = copied / elapsed if elapsed > 0 else 0.0
                rem = max(total - copied, 0)
                eta = int(rem / rate) if rate > 0 else None
                copied_mb = copied / (1024 * 1024)
                total_mb = total / (1024 * 1024) if total > 0 else 0.0
                rate_mb = rate / (1024 * 1024)
                eta_s = f"{eta}s" if eta is not None else "??s"
                print(
                    f"[sift] transfer: copying {src.name} — {pct}% ({copied_mb:.1f}/{total_mb:.1f} MB) @ {rate_mb:.2f} MB/s ETA {eta_s}",
                    flush=True,
                )
                last_print_pct = pct

    # Preserve metadata like permissions/times; allow this to raise if it fails
    shutil.copystat(src, dst)


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


def _find_existing_variant(dst: Path) -> Path | None:
    """Return an existing file that matches dst or a deduped variant.

    Looks in the destination's parent directory for either the exact
    destination name or names produced by _dedup_path ("name (n).ext").
    """

    parent = dst.parent
    if not parent.exists():
        return None

    stem = dst.stem
    suffix = dst.suffix
    dedup_pat = re.compile(rf"^{re.escape(stem)} \((\d+)\){re.escape(suffix)}$")

    for p in parent.iterdir():
        if not p.is_file():
            continue
        name = p.name
        if name == dst.name or dedup_pat.match(name):
            return p
    return None


def compute_destination(
    cfg: SiftConfig, item: Dict[str, Any]
) -> Tuple[str, str, Path, Dict[str, Any]]:
    """
    Compute final destination:

      outgoing_root/{movies|tv}/{tier.folder}/{relpath}

    Returns (media_type, tier_id, dst_path, facts)
    """
    media_type, tier, rel_dest, facts = route_destination(cfg, item)
    # If a proposed_name is present in the inventory, prefer that as the rel_dest
    prop = item.get("proposed_name")
    if isinstance(prop, str) and prop:
        rel_dest = Path(prop)
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

        # Skip items marked as samples (too short, no video, or shorter variants)
        skip_reason = item.get("skip_reason")
        if skip_reason:
            skipped += 1
            details.append(
                {
                    "relpath": rel,
                    "src": str(src),
                    "action": "skip",
                    "reason": skip_reason,
                }
            )
            continue

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

        # proposed_name is the basename we will write to in the destination
        proposed_name = dst.name

        # Check early for the computed destination or any deduped variant
        # already present in the destination parent directory. If found, skip
        # to avoid writing additional copies of the same logical file.
        existing_variant = _find_existing_variant(dst)
        if existing_variant:
            skipped += 1
            details.append(
                {
                    "relpath": rel,
                    "src": str(src),
                    "dst": str(dst),
                    "proposed_name": proposed_name,
                    "action": "skip",
                    "reason": "already_processed",
                    "existing_path": str(existing_variant),
                    "media_type": media_type,
                    "tier_id": tier_id,
                    "facts": facts,
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
                        "proposed_name": proposed_name,
                        "action": "skip",
                        "reason": "source_missing",
                        "media_type": media_type,
                        "tier_id": tier_id,
                        "facts": facts,
                    }
                )
                continue

            # If a file with the same destination path already exists, skip
            if dst.exists():
                if _same_file(src, dst):
                    skipped += 1
                    details.append(
                        {
                            "relpath": rel,
                            "src": str(src),
                            "dst": str(dst),
                            "proposed_name": proposed_name,
                            "action": "skip",
                            "reason": "already_present_samefile",
                            "media_type": media_type,
                            "tier_id": tier_id,
                            "facts": facts,
                        }
                    )
                    continue

                # Existing destination means this logical file was already
                # processed; skip instead of writing another deduped copy.
                skipped += 1
                details.append(
                    {
                        "relpath": rel,
                        "src": str(src),
                        "dst": str(dst),
                        "proposed_name": proposed_name,
                        "action": "skip",
                        "reason": "already_processed",
                        "media_type": media_type,
                        "tier_id": tier_id,
                        "facts": facts,
                    }
                )
                continue

            _ensure_parent(dst, mkdirs=cfg.io.mkdirs)

            if dry_run:
                # Print a short progress message so users can see we are working
                print(
                    f"[sift] transfer: would {cfg.io.mode} {src} -> {dst}", flush=True
                )
                details.append(
                    {
                        "relpath": rel,
                        "src": str(src),
                        "dst": str(dst),
                        "proposed_name": proposed_name,
                        "action": f"{cfg.io.mode}_dry_run",
                        "media_type": media_type,
                        "tier_id": tier_id,
                        "facts": facts,
                    }
                )
                continue

            if cfg.io.mode == "copy":
                # Start copy with progress reporting
                print(f"[sift] transfer: copying {src} -> {dst}", flush=True)
                _copy_with_progress(src, dst)
                copied += 1
                details.append(
                    {
                        "relpath": rel,
                        "src": str(src),
                        "dst": str(dst),
                        "proposed_name": proposed_name,
                        "action": "copied",
                        "media_type": media_type,
                        "tier_id": tier_id,
                        "facts": facts,
                    }
                )
            elif cfg.io.mode == "move":
                # Attempt fast rename first; if cross-device, fallback to copy+remove with progress
                print(f"[sift] transfer: moving {src} -> {dst}", flush=True)
                try:
                    os.rename(src, dst)
                    moved += 1
                except OSError:
                    # cross-device; copy with progress then remove src
                    _copy_with_progress(src, dst)
                    try:
                        os.remove(src)
                    except OSError:
                        # non-fatal: leave file and record failure
                        raise
                    moved += 1

                details.append(
                    {
                        "relpath": rel,
                        "src": str(src),
                        "dst": str(dst),
                        "proposed_name": proposed_name,
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
                        "proposed_name": proposed_name,
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
                    "proposed_name": proposed_name,
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
