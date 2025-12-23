from pathlib import Path

from sift.cli import main


def _cfg_text_with_paths(tmp_path: Path) -> str:
    # Read example config and substitute our tmp paths for paths.*
    base = Path(__file__).resolve().parents[1]
    ex = (base / "config.example.toml").read_text()

    # Replace the sample paths with tmp paths
    ex = ex.replace(
        'incoming = "/nas/plex/incoming"', f'incoming = "{tmp_path / "incoming"}"'
    )
    ex = ex.replace(
        'outgoing_root = "/nas/plex/test"', f'outgoing_root = "{tmp_path / "outgoing"}"'
    )
    ex = ex.replace(
        'metadata_cache = "/nas/plex/.cache/ffprobe"',
        f'metadata_cache = "{tmp_path / "cache"}"',
    )
    # Also ensure report path is inside tmp_path to avoid touching /nas
    ex = ex.replace(
        'report_path = "/nas/plex/intake-report.jsonl"',
        f'report_path = "{tmp_path / "report.jsonl"}"',
    )
    return ex


def test_apply_wins_and_no_misleading_dry_run_message(tmp_path, capsys):
    # Create a temp config file based on the example but pointing at tmp dirs
    cfg_text = _cfg_text_with_paths(tmp_path)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(cfg_text)

    # Ensure incoming dir exists but is empty
    (tmp_path / "incoming").mkdir()

    # Run main with both --dry-run and --apply: --apply should win and there should be no DRY RUN banner
    exit_code = main(["--config", str(cfg_file), "--dry-run", "--apply"])
    captured = capsys.readouterr()

    # When both provided, we should NOT see the DRY RUN banner
    assert "DRY RUN (no filesystem changes)" not in captured.out
    # We should still return an exit code (0 or 5 depending on failures); assert function returned an int
    assert isinstance(exit_code, int)


def test_effective_dry_run_prints_banner(tmp_path, capsys):
    cfg_text = _cfg_text_with_paths(tmp_path)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(cfg_text)

    # Ensure incoming dir exists
    (tmp_path / "incoming").mkdir()

    # Now run only --dry-run without --apply and ensure the banner appears
    exit_code = main(["--config", str(cfg_file), "--dry-run"])  # no --apply
    captured = capsys.readouterr()
    assert "DRY RUN (no filesystem changes)" in captured.out
    assert isinstance(exit_code, int)
