# Specification

**Product:** sift v2 (see `docs/spec/product.md`)
**Spec version:** 0.1.0

The spec is the single source of truth for what the product does and how. Only the architect edits it. Agents may add traceability rows and dependency pins when a card says so.

## Versioning

`MAJOR.MINOR.PATCH`, recorded only in this file.

- PATCH: wording, clarification, no change to behaviour.
- MINOR: new or changed requirement. While MAJOR is 0, a change to any contract (an interface, a data shape, a rule) is also MINOR.
- MAJOR: incompatible change after 1.0.0.

Every change adds a row to the changelog in the same PR.

## Changelog

| Version | Date | Change | Requirements | PR |
|---|---|---|---|---|
| 0.1.0 | 2026-10-11 | Initial spec: v2 product definition and phase 1 (gather data) requirements | PRB, SRV, PLX, CTL, FIX, GRD | |

## Requirements

One file per area under `docs/spec/`, named for the area (for example `docs/spec/sync.md`). This file keeps the index.

### Requirement format

```
### <PREFIX>-FR-<n>: <short title>

<The requirement, one testable statement.>

**Acceptance:** what can be observed when it is met (an outcome, not an implementation).
**Tests:** the named tests that prove it.
**Guard:** (only for rules that matter) the static test that fails the build if the rule is broken.
**Depends on:** other requirement IDs.
```

Rules for writing a requirement:

1. One requirement states one thing. If it needs "and", split it.
2. Acceptance describes outcomes someone can see, not how the code works.
3. Check the new requirement against its neighbours before merging. Two requirements that cannot both be true are a defect in the spec.
4. Every requirement names its tests. A requirement with no test is a wish.

### Index

| ID | Title | Area | Status |
|---|---|---|---|
| PRB-FR-1 | Record every stream | spec/probe.md | draft |
| PRB-FR-2 | Keep the v1 summary fields | spec/probe.md | draft |
| PRB-FR-3 | Cache per file | spec/probe.md | draft |
| PRB-FR-4 | New files are found without a rescan | spec/probe.md | draft |
| PRB-FR-5 | Probe timeout | spec/probe.md | draft |
| SRV-FR-1 | Survey is read-only | spec/survey.md | draft |
| SRV-FR-2 | One row per file | spec/survey.md | draft |
| SRV-FR-3 | Corpus summary | spec/survey.md | draft |
| SRV-FR-4 | Audio selection candidates | spec/survey.md | draft |
| SRV-FR-5 | Where the report goes | spec/survey.md | draft |
| PLX-FR-1 | Credentials come from the environment | spec/plex.md | draft |
| PLX-FR-2 | The Plex client only reads | spec/plex.md | draft |
| PLX-FR-3 | Snapshot of libraries, parts and streams | spec/plex.md | draft |
| PLX-FR-4 | Join Plex to the inventory | spec/plex.md | draft |
| PLX-FR-5 | Where Plex disagrees with the file | spec/plex.md | draft |
| PLX-FR-6 | Observe what Plex does at play time | spec/plex.md | draft |
| PLX-FR-7 | Observations are keyed to the library | spec/plex.md | draft |
| CTL-FR-1 | Manifest format and validator | spec/control.md | draft |
| CTL-FR-2 | One report per control title | spec/control.md | draft |
| CTL-FR-3 | Control data stays out of git | spec/control.md | draft |
| FIX-FR-1 | Export sanitised fixtures | spec/fixtures.md | draft |
| FIX-FR-2 | Committed fixtures use an allowlist | spec/fixtures.md | draft |
| GRD-FR-1 | Destructive operations only in the allowlist | spec/safety.md | draft |
| GRD-FR-2 | Plex client is GET only | spec/safety.md | draft |
| GRD-FR-3 | Token never in output | spec/safety.md | draft |
| GRD-FR-4 | Real data stays out of git | spec/safety.md | draft |

## Traceability

Agents add a row when a story implements a requirement.

| Requirement | Story | PR | Tests |
|---|---|---|---|
| | | | |
