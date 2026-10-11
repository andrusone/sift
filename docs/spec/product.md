# Product: sift v2

## Intent

For every media file the owner has ripped, sift answers two questions from the file's real streams, not its name:

1. **Will it play on Plex and Apple TV as-is?** Sorted into two buckets: `plex-ok` and `plex-incompatible`, with a reason.
2. **What is in it?** A uniform, consistent set of tags in the file name for video and audio format, so the quality is unmistakable at a glance.

Version 1 ranked files into quality tiers to decide what was worth keeping. Version 2 keeps the same pipeline (probe, decide, name, place) but changes what is decided. "Worth keeping" is no longer the question; "will it play, and what is it" is.

## The problem to solve first

Ripped discs (mostly Ultra HD Blu-ray, some Blu-ray and DVD) often carry several audio tracks, for example an English DTS track Plex and Apple TV cannot use well, and an AC3 track they can. Today the player does not pick the AC3 track, and sift cannot even see that the second track exists, because v1 keeps one "best" audio stream per file. Version 2 must make this visible, then fix it without per-file manual work, or at least give the owner a way to choose from the remote at play time.

## Constraints

- Source content varies and is not under the owner's control: UHD, Blu-ray and DVD, many rippers, no consistent layout. Re-ripping for consistency is out of scope. sift adapts to the files it is given.
- sift runs on a schedule on a headless Linux VM where Plex lives. It is a command-line tool; its output must be useful to a person reading a report and to the next scheduled run.
- The owner's library is about 200 titles. Everything is read from disk and from Plex; nothing is guessed from file names.
- The repository is public. Library details never enter it (see `docs/SAFETY.md`).

## Vocabulary

| Term | Meaning |
|---|---|
| Stream | One video, audio or subtitle track inside a file, as `ffprobe` reports it. |
| Default stream | The track the file itself marks as default (the `default` disposition). If none is marked, the first of that type. |
| Direct Play | Plex sends the file as-is and the client plays every stream. |
| Direct Stream | Plex repackages the container or transcodes audio only; video is untouched. |
| Transcode | Plex re-encodes video. |
| Control set | The 3 to 15 titles the owner has found that do not play correctly, plus a few that do, with what was observed on the owner's player. It is the test oracle for every later decision. |
| Observation | What was seen, not what the rules predicted. Observations come from Plex and from the owner. |

## Three phases

1. **Gather the data we need to decide.** Make every stream visible. Survey the whole library. Capture what Plex actually does with the control set. Output is data and a questions list, not decisions.
2. **Validate the assumptions and test the decisions.** Turn the data into candidate rules for "compatible", replay them against the control set and the whole library, and settle the open decisions with evidence.
3. **Make the decisions and fulfil the requirements.** Replace tiers with the compatibility verdict, two-bucket placement, the uniform tag grammar, and the audio fix. Harden transfer for unattended runs.

Phases 2 and 3 are deliberately not specified yet. Writing their requirements now would be guessing; phase 1 exists to remove the guesses.

## Open decisions (answered in phase 2, with evidence)

| Question | Why it matters |
|---|---|
| Which player defines "compatible": Plex on Apple TV, Infuse, or both? | Infuse and the Plex app handle Dolby Vision profile 7 and lossless audio differently. |
| Is Direct Stream (audio transcode only) acceptable, or is it "incompatible"? | Decides whether TrueHD or DTS-HD files with no AC3 track are in `plex-ok`. |
| What does Plex expose about which audio track it auto-selects, and when? | Decides whether the problem can be observed from the library or only during playback. Phase 1 gathers this (PLX-FR-6). |
| Is Plex's per-file default audio setting usable, or must the fix be in the file? | Decides the shape of the audio fix. Needs the owner's approval to write to Plex (`docs/SAFETY.md`, rule 3). |

## Non-goals

- Downloading, indexers, online metadata lookups.
- Re-encoding video. Remuxing (changing tracks and flags without re-encoding) is in scope for phase 3; transcoding is not.
- A graphical interface or a long-running service.
- Judging whether a file is "worth keeping".
