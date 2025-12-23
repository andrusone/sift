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

- Linux
- `ffprobe` (from FFmpeg)
- Python **3.11+**

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

`sift` caches `ffprobe` results for speed. To ignore the cache and re-scan all files:

```bash
sift --config config.toml --rescan
```

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
