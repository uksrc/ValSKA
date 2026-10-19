# BayesEoR operations CLI (ValSKA)

This page documents the operational helper CLIs used after sweep preparation/submission:

- `valska-bayeseor-help`
- `valska-bayeseor-resume`
- `valska-bayeseor-report-all`
- `valska-bayeseor-compare-sweeps`
- `valska-bayeseor-cleanup`

These commands are intended for recovery, reporting at campaign scale, comparison of outcomes, and safe maintenance.

Naming conventions used in this page:

- `run_id`: identifier stored in sweep metadata
- `sweep_dir`: `_sweeps/<run_id>` directory containing `sweep_manifest.json`
- `run_dir`: one per-point directory referenced by a sweep point row

---

## 0) Command index / discoverability

`valska-bayeseor-help` prints a concise summary of BayesEoR commands grouped by topic.

Basic usage:

```bash
valska-bayeseor-help
```

Filter by topic:

```bash
valska-bayeseor-help --topic reporting
valska-bayeseor-help --topic operations
```

Machine-readable output:

```bash
valska-bayeseor-help --json
```

Topics currently supported:

- `setup`
- `submission`
- `reporting`
- `health`
- `operations`

---

## 1) Resume incomplete sweep points

`valska-bayeseor-resume` inspects one sweep and prints exact `valska-bayeseor-submit` commands for missing work.

Basic usage:

```bash
valska-bayeseor-resume /path/to/_sweeps/<run_id>
```

Generate only GPU-stage suggestions:

```bash
valska-bayeseor-resume /path/to/_sweeps/<run_id> --stage gpu
```

Generate only CPU-stage suggestions:

```bash
valska-bayeseor-resume /path/to/_sweeps/<run_id> --stage cpu
```

Machine-readable output:

```bash
valska-bayeseor-resume /path/to/_sweeps/<run_id> --json
```

Key behaviour:

- skips already-complete points
- emits minimal command set needed per point
- can include notes about missing `jobs.json` or detected CPU job-id hints

---

## 2) Batch reporting across discovered sweeps

`valska-bayeseor-report-all` discovers sweeps under `results_root` and runs `valska-bayeseor-report` logic for each selected sweep.

Default run:

```bash
valska-bayeseor-report-all
```

Filter by campaign dimensions:

```bash
valska-bayeseor-report-all --beam airy_diam14m --sky GSM_plus_GLEAM
valska-bayeseor-report-all --run-id sweep_airy_init
valska-bayeseor-report-all --latest
```

Skip already-reported sweeps:

```bash
valska-bayeseor-report-all --only-new
```

No-plot batch mode (tables only):

```bash
valska-bayeseor-report-all --no-plots
```

Write reports under a separate root:

```bash
valska-bayeseor-report-all --out-root /path/to/report_mirror
```

JSON output and CI-friendly failure mode:

```bash
valska-bayeseor-report-all --json
valska-bayeseor-report-all --fail-on-error
```

Key behaviour:

- preserves per-sweep report structure and output files
- records generated/skipped/error counts in summary payload

---

## 3) Compare two sweep outcomes

`valska-bayeseor-compare-sweeps` compares per-point report metrics between two sweep summaries.

Accepted input forms for each side:

- sweep dir containing `report/sweep_report_summary.json`
- report dir containing `sweep_report_summary.json`
- direct path to `sweep_report_summary.json`

Basic usage:

```bash
valska-bayeseor-compare-sweeps /path/to/sweep_A /path/to/sweep_B
```

Choose comparison metric:

```bash
valska-bayeseor-compare-sweeps /path/to/A /path/to/B \
  --metric log10_bayes_factor_signal_over_no_signal
```

Show only top-N largest absolute deltas:

```bash
valska-bayeseor-compare-sweeps /path/to/A /path/to/B --top 20
```

Machine-readable output with labels:

```bash
valska-bayeseor-compare-sweeps /path/to/A /path/to/B \
  --left-name baseline --right-name trial --json
```

Compared metric is interpreted as `right - left`.

Summary includes:

- shared / left-only / right-only point counts
- status mismatch counts
- compared points and skipped-missing-metric counts
- mean/min/max delta statistics

---

## 4) Cleanup (safe-by-default maintenance)

`valska-bayeseor-cleanup` supports maintenance cleanup with strong safety controls.

Important defaults:

- default mode is **dry-run** (no filesystem changes)
- by default, execution uses move-to-trash mode (reversible)
- hard deletion requires explicit `--hard-delete`
- run-directory removal requires explicit confirmation token

### Scope selection

Choose one or more scopes:

```bash
--prune-logs
--prune-temp
--prune-runs
```

or all scopes:

```bash
--all
```

### Dry-run preview

Preview all cleanup candidates:

```bash
valska-bayeseor-cleanup --all --json
```

### Execute log cleanup (reversible)

```bash
valska-bayeseor-cleanup --prune-logs --execute
```

### Execute run-directory cleanup (requires confirmation)

Run cleanup for missing points only:

```bash
valska-bayeseor-cleanup \
  --prune-runs \
  --run-status missing \
  --execute \
  --confirm-runs DELETE
```

Optional hard-delete mode:

```bash
valska-bayeseor-cleanup \
  --prune-runs \
  --run-status missing \
  --execute \
  --confirm-runs DELETE \
  --hard-delete
```

Age gate:

```bash
valska-bayeseor-cleanup --prune-logs --older-than-days 14 --execute
```

Filtering options mirror sweep discovery tools:

- `--run-id`, `--beam`, `--sky`, `--latest`, `--max-results`

CI-friendly behaviour:

```bash
valska-bayeseor-cleanup --prune-logs --execute --fail-on-error
```

---

## Suggested operational sequence

For large campaigns, a practical order is:

1. `valska-bayeseor-sweep-audit` (health + validation overview)
2. `valska-bayeseor-resume` (generate exact missing-stage commands)
3. `valska-bayeseor-report-all` (refresh campaign-wide reports)
4. `valska-bayeseor-compare-sweeps` (compare baseline vs trial)
5. `valska-bayeseor-cleanup` (dry-run first; execute only when ready)

---

## Wrapper scripts (bash)

Shell wrappers are available under `bash_scripts/` for these commands:

- `bash_scripts/valska-bayeseor-help.sh`
- `bash_scripts/valska-bayeseor-resume-sweep.sh`
- `bash_scripts/valska-bayeseor-report-all.sh`
- `bash_scripts/valska-bayeseor-compare-sweeps.sh`
- `bash_scripts/valska-bayeseor-cleanup.sh`

Each wrapper follows the same fallback order:

1. use the CLI directly from `PATH`
2. fall back to `conda run -n <VALSKA_CONDA_ENV>`
3. fall back to local module execution (`PYTHONPATH=src python -m ...`)

Set the optional environment variable if needed:

```bash
export VALSKA_CONDA_ENV=valska
```

---

## Future direction (roadmap note)

Current tooling uses separate command entry points (for example, `valska-bayeseor-sweep`,
`valska-bayeseor-report`, `valska-bayeseor-cleanup`).

A future simplification path is to add a single root command with subcommands:

```bash
valska-bayeseor <subcommand> [...]
```

This is intentionally tracked as a future migration idea to preserve current stable workflows
while improving discoverability and shared option handling over time.
