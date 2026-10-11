# GitHub bootstrap

Configures what a GitHub template repo cannot copy. Run it once after creating a repo from the template.

| Step | What it does |
|---|---|
| `labels` | Creates or updates the labels in `config/labels.tsv` (story, decision, blocked, waiting, guardrail, ...). Leaves existing labels alone. |
| `settings` | Squash merge only, delete branch on merge, wiki off, issues and projects on. |
| `project` | Creates a Projects v2 board titled after the repo, links it, sets the Status options (Backlog, Preparing, Ready, In progress, Blocked, Done), and adds the fields Estimate, Value, Score, Sprint, Waiting on. |
| `protection` | Protects `main`: PR required, linear history, no force-push or deletion, conversations resolved, optional required CI checks. |
| `sprint-log` | Creates and pins the sprint log issue. |

## Usage

Safe by default: without `--apply` it only reads GitHub and prints a plan.

```bash
./bootstrap.sh                                   # plan
./bootstrap.sh --apply
./bootstrap.sh --only labels,project --apply
./bootstrap.sh --required-checks "windows,ubuntu" --only protection --apply
```

```powershell
.\bootstrap.ps1
.\bootstrap.ps1 -Apply
.\bootstrap.ps1 -RequiredChecks windows,ubuntu -Only protection -Apply
```

Both scripts read the same files in `config/`. Edit those to change policy; do not edit the scripts.

## Guarantees

- Idempotent: re-running converges.
- Never deletes anything.
- Only touches a project whose title exactly matches `--project-title` (default: the repo name). Other boards on the account are never read or changed beyond listing titles.

## Known limits

- **Branch protection needs a public repo or a paid plan.** On a private repo without it GitHub returns 403; the script warns and continues. Re-run `--only protection --apply` once the repo is public.
- **Score is not a formula.** Projects v2 has no formula fields, so Score (Value / Estimate) is set by the architect or by automation.
- **Sprint is a text field.** `gh` cannot create iteration fields.
- **Status options use the GraphQL `updateProjectV2Field` mutation** because `gh project` cannot edit them. This replaces the default options, which is safe on a new board but would clear column assignments on a board that already has items.
- Required checks default to none because the template has no CI yet. Pass them when CI exists.
