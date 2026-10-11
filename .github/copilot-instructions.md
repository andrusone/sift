# Instructions for GitHub Copilot

Read these from `origin/main` at the start of every session and follow them exactly:

1. `docs/STARTER_PROMPT.md`: how to work (process).
2. `docs/SAFETY.md`: what you must never do (safety).

The spec is `docs/SPEC.md`. You do not edit it.

## This project

sift is a Python command-line tool that runs on a headless Linux VM next to Plex. It reads real stream metadata with `ffprobe`, decides whether each media file will play on Plex and Apple TV as-is, and sorts and names files so the answer is visible. Version 2 is in progress; the plan is in `docs/spec/product.md`.

## Build, test and lint

Python 3.12 or newer. From the repository root:

```bash
python -m pip install -e . pytest "black>=25.12,<26" "ruff>=0.14.10,<0.15"
python -m pytest
python -m ruff check .
python -m black --check .
```

Tests must not need `ffprobe`, a network or a real media file. Use recorded `ffprobe` JSON and temporary directories. Source is in `src/sift/`, tests in `tests/`.

## Pinned tools

Versions are pinned in `pyproject.toml` and `poetry.lock`, and in `.pre-commit-config.yaml`. Do not upgrade pinned tools.
