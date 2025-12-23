from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .config import load_toml, parse_config
from .errors import CacheError, ConfigError
from .inventory import build_inventory
from .scaffold import ensure_dirs, planned_folders
from .transfer import transfer_inventory
from .utils import as_path


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sift",
        description="Media intake: ffprobe incoming media, cache metrics, and optionally copy/move into outgoing_root.",
    )
    p.add_argument(
        "--config",
        default="config.toml",
        help="Path to config TOML (default: ./config.toml).",
    )
    p.add_argument(
        "--print-config",
        action="store_true",
        help="Print parsed config summary and exit (debug).",
    )
    p.add_argument(
        "--print-folders",
        action="store_true",
        help="Print folders that would be created and exit.",
    )
    p.add_argument(
        "--rescan",
        action="store_true",
        help="Force a fresh scan + ffprobe and overwrite the cache.",
    )
    p.add_argument(
        "--limit", type=int, default=None, help="Cap how many files are probed (debug)."
    )
    p.add_argument(
        "--only-ext",
        action="append",
        default=None,
        help="Restrict scanning to extensions (repeatable).",
    )

    # NEW: transfer controls
    p.add_argument(
        "--apply",
        action="store_true",
        help="Perform the configured io.mode action (copy/move) into outgoing_root/_intake.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied/moved without touching the filesystem.",
    )
    p.add_argument(
        "--only-ok-ffprobe",
        action="store_true",
        help="Only transfer files where ffprobe succeeded (ffprobe.ok == true).",
    )
    p.add_argument(
        "--write-transfer-report",
        default=None,
        help="Optional path to write a JSON transfer report (details for every file).",
    )
    return p


def print_config_summary(cfg) -> None:
    print("sift config summary")
    print("-------------------")
    print(f"incoming      : {cfg.paths.incoming}")
    print(f"outgoing_root : {cfg.paths.outgoing_root}")
    print(f"metadata_cache: {cfg.paths.metadata_cache}")
    print(f"mode          : {cfg.io.mode}")
    print(f"mkdirs        : {cfg.io.mkdirs}")
    print(f"dedupe        : {cfg.io.dedupe_on_collision}")
    print(f"ffprobe       : {cfg.ffprobe.bin} {' '.join(cfg.ffprobe.args)} <file>")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    cfg_path = as_path(str(args.config))
    try:
        root = load_toml(cfg_path)
        cfg = parse_config(root)
    except ConfigError as e:
        print(f"[sift] config error: {e}", file=sys.stderr)
        return 2

    if args.print_config:
        print_config_summary(cfg)
        return 0

    if args.print_folders:
        for p in planned_folders(cfg):
            print(p)
        return 0

    if cfg.io.mkdirs:
        ensure_dirs(cfg)

    try:
        inv = build_inventory(
            cfg,
            rescan=bool(args.rescan),
            only_ext=list(args.only_ext) if args.only_ext else None,
            limit=args.limit,
        )
    except (ConfigError, CacheError, OSError) as e:
        print(f"[sift] inventory error: {e}", file=sys.stderr)
        return 3

    count = int(inv.get("count", 0))
    errors = int(inv.get("errors", 0))
    print(
        f"[sift] inventory: {count} files (errors={errors}) -> {cfg.paths.metadata_cache / 'scan.json'}"
    )

    # NEW: apply transfer step
    if args.apply or args.dry_run:
        if cfg.io.mode not in {"copy", "move"}:
            print(f"[sift] invalid io.mode: {cfg.io.mode}", file=sys.stderr)
            return 4

        # --apply wins when both provided; compute the effective dry_run flag once
        effective_dry_run = bool(args.dry_run) and not bool(args.apply)
        if effective_dry_run:
            print("[sift] transfer: DRY RUN (no filesystem changes)")

        result = transfer_inventory(
            cfg,
            inv,
            dry_run=effective_dry_run,
            only_ok_ffprobe=bool(args.only_ok_ffprobe),
        )

        # Summary first (INTJ-friendly)
        print(
            "[sift] transfer summary: "
            f"copied={result.copied} moved={result.moved} skipped={result.skipped} failed={result.failed}"
        )

        # Optional report
        if args.write_transfer_report:
            rp = as_path(str(args.write_transfer_report))
            rp.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "mode": cfg.io.mode,
                "dry_run": bool(args.dry_run) and not bool(args.apply),
                "copied": result.copied,
                "moved": result.moved,
                "skipped": result.skipped,
                "failed": result.failed,
                "details": result.details,
            }
            rp.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"[sift] wrote transfer report: {rp}")

        # Non-zero if any failures
        return 5 if result.failed else 0

    return 0
