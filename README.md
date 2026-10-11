# sift

**Sift media. Keep signal.**

`sift` is a small, opinionated tool for deciding whether a media file is
**technically worth keeping**.

It looks at the *actual* video and audio streams (via `ffprobe`), assigns a
quality/compatibility tier, and drops the file into an organized intake folder
with a clear, honest filename.

You review the result.
You decide what stays.

> Not related to the DFIR “SIFT Workstation” or computer-vision SIFT algorithms.

> **Version 2 is in progress.** The goal is changing from "is this worth keeping?" to "will this play on Plex and Apple TV, and what exactly is in it?". This README describes version 1, which still works. The plan is in [docs/spec/product.md](docs/spec/product.md); the work is tracked on the project board. See [Developing sift](#developing-sift).

---

## The problem

Most media tools focus on *what* a file is:
movie title, episode name, release group.

`sift` focuses on something simpler and more annoying:

- Will this direct-play cleanly?
- Is this a good encode, or just “big”?
- Is this something I should keep, or replace later?

If you’ve ever thought *“this looks fine, but I don’t trust it”*, this tool is for you.

---

## What sift does

For each file in an **incoming** folder, `sift` will:

- inspect real stream metadata (not filenames)
- normalize what matters:
  - resolution
  - HDR
  - video codec
  - audio codec and channel layout
- assign a tier (good / acceptable / replace)
- rename the file so the truth is visible at a glance
- move or copy it into an **intake** structure for review

Nothing is deleted.
Nothing touches your existing library.

---

## What sift intentionally does *not* do

- No downloading
- No indexers
- No online metadata lookups by default
- No “smart guesses” you can’t explain later

`sift` is a gate, not a manager.

---

## Tiers (default model)

The defaults are opinionated and Apple-TV-aware. You can change them.

- **T1 — Reference**
  2160p, HDR, HEVC/AV1, DDP 5.1+

- **T2 — Excellent**
  2160p, HEVC, DD/DDP 5.1+, HDR optional

- **T3 — Good**
  1080p, H264/HEVC, AAC/DD/DDP

- **T4 — Low quality**
  720p or SD, clearly suboptimal

- **T5 — Incompatible**
  Audio that commonly forces bad transcodes (TrueHD, DTS-HD MA)

The tiers exist to answer one question:
**is this worth keeping?**

---

## How it’s meant to be used

1. Drop new files into an incoming folder
2. Run `sift`
3. Look at the output
4. Decide what to promote, replace, or delete

That’s it.

---

## Installation

### Requirements

- Linux (the VM where Plex lives; development on other systems is fine)
- `ffprobe` (from FFmpeg)
- Python **3.12+**

---

### Install FFmpeg / ffprobe

On Ubuntu or Debian:

```bash
sudo apt update
sudo apt install ffmpeg
```

Verify:

```bash
ffprobe -version
```

---

### Install `sift`

`sift` is a standalone Python tool. You do **not** need Poetry to use it.

#### Option 1: Install with `pipx` (recommended)

`pipx` installs Python tools in isolated environments and exposes them as normal commands.

```bash
sudo apt install pipx
pipx ensurepath
```

Then install `sift` from the repository:

```bash
pipx install git+https://github.com/andrusone/sift.git
```

Verify:

```bash
sift --help
```

---

#### Option 2: Install with `pip` (system or virtualenv)

```bash
python3 -m pip install git+https://github.com/andrusone/sift.git
```

This installs the `sift` command into your active Python environment.

---

#### Option 3: Run without installing (advanced / dev)

From a cloned repository:

```bash
python -m sift.cli --config config.toml
```

---

## Configuration

`sift` is driven entirely by a TOML file.

1. Copy the example config:

```bash
cp config.example.toml config.toml
```

2. Edit the paths to match your system:

```toml
[paths]
incoming = "/nas/plex/incoming"
outgoing_root = "/nas/plex/intake"
metadata_cache = "/nas/plex/.cache/ffprobe"
```

Everything else has safe defaults and is meant to be read and understood.

---

## Usage

### Basic run

```bash
sift --config config.toml
```

By default, files are **copied** (not moved) into the intake structure defined by your tiers.

---

### Dry run (recommended first)

See what would happen without touching the filesystem:

```bash
sift --config config.toml --dry-run
```

---

### Force a rescan of media files

`sift` caches `ffprobe` results and classification decisions for speed.

**Important:** When you modify classification logic (tier rules, resolution thresholds, codec mappings, etc.) in `config.toml`, you **must** use `--rescan` to regenerate the cache with the new rules:

```bash
sift --config config.toml --rescan
```

Without `--rescan`, sift will use the cached classifications from the previous configuration.

---

### Generate a transfer report

Write a JSON report describing every decision made:

```bash
sift --config config.toml --dry-run --write-transfer-report /tmp/sift-transfer.json
```

Inspect results:

```bash
jq '.details[] | [.tier_id, .relpath] | @tsv' /tmp/sift-transfer.json
```

---

## Typical workflow

1. Drop new files into the **incoming** folder
2. Run `sift --dry-run`
3. Review the output folders and filenames
4. Re-run without `--dry-run` when satisfied
5. Manually promote, replace, or delete files

`sift` never deletes your media.
It only helps you decide what’s worth keeping.

---

## Developing sift

sift is built with the [OneFoundry](https://github.com/andrusone/onefoundry) operating model: a product owner decides what and why, an architect writes the spec and reviews, and coding agents build one small story at a time.

- Product intent and phases: [docs/spec/product.md](docs/spec/product.md)
- Requirements: [docs/SPEC.md](docs/SPEC.md) and [docs/spec/](docs/spec/)
- How the work flows: [docs/OPERATING-MODEL.md](docs/OPERATING-MODEL.md)
- What must never happen: [docs/SAFETY.md](docs/SAFETY.md)

Build and test:

```bash
python -m pip install -e . pytest "black>=25.12,<26" "ruff>=0.14.10,<0.15"
python -m pytest
python -m ruff check .
python -m black --check .
```
