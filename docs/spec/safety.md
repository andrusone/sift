# Guards (GRD)

Static tests that enforce `docs/SAFETY.md`. They scan the source rather than exercise behaviour, so they fail the build the moment a rule is broken.

### GRD-FR-1: Destructive operations only in the allowlist

Calls that destroy or replace data (`os.remove`, `os.unlink`, `os.replace`, `os.rename`, `shutil.rmtree`, `shutil.move`, `Path.unlink`, `Path.rename`, `Path.replace`, `Path.write_text`/`write_bytes` and `open(..., "w"|"wb"|"a")` on media paths) appear only in the functions listed in `tests/guard_allowlist.py`. Today that is `src/sift/transfer.py` and the cache and report writers. Anything else fails the test.

**Acceptance:** adding `os.remove(x)` to `src/sift/survey.py` makes the test fail and names the file and line.
**Tests:** `test_destructive_ops_only_in_allowlist`, `test_guard_detects_a_violation` (runs the scanner on a temporary file containing one).
**Depends on:** none.

### GRD-FR-2: Plex client is GET only

No module that talks to Plex uses a request method other than GET. The scanner fails on `POST`, `PUT`, `DELETE`, `PATCH` or a call that passes a `data=`/`json=` body.

**Acceptance:** a temporary module containing a `PUT` is rejected by the scanner.
**Tests:** `test_plex_client_get_only`, `test_guard_detects_plex_write`.
**Depends on:** none.

### GRD-FR-3: Token never in output

A test sets `PLEX_TOKEN` to a fake value, runs each Plex command against a fake server including error paths, and asserts the value is absent from stdout, stderr, log records and written files.

**Acceptance:** adding `print(token)` anywhere in the Plex path makes the test fail.
**Tests:** `test_plex_token_never_in_output`.
**Depends on:** none.

### GRD-FR-4: Real data stays out of git

`var/` is in `.gitignore`, and no tracked file lives under `var/`.

**Acceptance:** removing `var/` from `.gitignore` fails the test.
**Tests:** `test_var_dir_is_gitignored`.
**Depends on:** none.
