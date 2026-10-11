# Spec areas

One file per area of the product (for example `sync.md`, `ui.md`, `security.md`). Requirement IDs use a short prefix per area and are never reused. The index and the version live in `../SPEC.md`; area files carry no version of their own.

See `../SPEC.md` for the requirement format.

## Areas

| File | Prefix | Covers |
|---|---|---|
| `product.md` | none | Intent, vocabulary, phases, open decisions |
| `probe.md` | PRB | Per-stream probe data and the cache |
| `survey.md` | SRV | Read-only library survey |
| `plex.md` | PLX | Read-only Plex snapshot and play-time observation |
| `control.md` | CTL | The control set of known good and bad titles |
| `fixtures.md` | FIX | Sanitised fixtures for a public repository |
| `safety.md` | GRD | Static guards that enforce `docs/SAFETY.md` |
