# BayesEoR CLI workflows (ValSKA)

This page is a practical, “example gallery”-style guide to running BayesEoR validation workflows using ValSKA.

It is written to be:
- copy/paste friendly (commands shown as fenced code blocks)
- HPC-friendly (explicit about dry-runs, SLURM submission, and dependencies)
- reproducible (paths, templates, and variants recorded in manifests)

If you are new, start with **Quick Start**. If you are iterating on a validation campaign, use **Detailed examples**.

---

## Contents

- [Quick Start](#quick-start)
  - [Before You Start](#before-you-start)
  - [CLI quick reference](#cli-quick-reference)
  - [Quick Definitions](#quick-definitions)
  - [Which command should I use?](#which-command-should-i-use)
  - [valska-bayeseor-help](#valska-bayeseor-help)
  - [valska-bayeseor-prepare](#valska-bayeseor-prepare)
  - [valska-bayeseor-sweep](#valska-bayeseor-sweep)
  - [valska-bayeseor-submit --stage cpu](#valska-bayeseor-submit---stage-cpu)
  - [valska-bayeseor-submit --stage gpu](#valska-bayeseor-submit---stage-gpu)
- [Concepts](#concepts)
  - [Beam / sky taxonomy (directory layout)](#beam--sky-taxonomy-directory-layout)
  - [Template + variant concept (collision-free template differences)](#template--variant-concept-collision-free-template-differences)
  - [What gets created where](#what-gets-created-where)
- [Lifecycle diagram](#lifecycle-diagram)
- [Detailed examples](#detailed-examples)
  - [A) Prepare (dry-run)](#a-prepare-dry-run)
  - [B) Prepare (real)](#b-prepare-real)
  - [C) Sweep (dry-run with point directories)](#c-sweep-dry-run-with-point-directories)
  - [D) Sweep (prepare only)](#d-sweep-prepare-only)
  - [E) Submit CPU+GPU together (fresh sweep)](#e-submit-cpugpu-together-fresh-sweep)
  - [F) Submit CPU across sweep points](#f-submit-cpu-across-sweep-points)
  - [G) Submit GPU across sweep points (after CPU)](#g-submit-gpu-across-sweep-points-after-cpu)
  - [H) Slurm array submission for sweep campaigns](#h-slurm-array-submission-for-sweep-campaigns)
  - [I) Advanced: per-point submission with valska-bayeseor-submit](#i-advanced-per-point-submission-with-valska-bayeseor-submit)
  - [J) Monitoring jobs](#j-monitoring-jobs)
  - [K) Post-processing reports (tables + plots)](#k-post-processing-reports-tables--plots)
  - [L) Sweep health/status checks](#l-sweep-healthstatus-checks)
  - [M) Aggregate sweep audit](#m-aggregate-sweep-audit)
  - [N) Backwards compatibility: deprecated --scenario](#n-backwards-compatibility-deprecated---scenario)

---

## Quick Start

### Before You Start

Before trying the workflow examples below, make sure you have completed the setup steps that ValSKA assumes:

ValSKA setup:

- install the `valska` environment so the `valska-bayeseor-*` CLI commands are available
  See the Installation section in the project README for environment setup details.

BayesEoR setup:

- clone BayesEoR locally in a location you control from [BayesEoR on GitHub](https://github.com/PSims/BayesEoR)
- create the BayesEoR conda environment using the environment file shipped with that BayesEoR checkout
- make sure the BayesEoR checkout and conda environment used by batch jobs are compatible with this ValSKA version

Runtime configuration in your ValSKA checkout:

- copy `config/runtime_paths.example.yaml` to `config/runtime_paths.yaml` in your ValSKA repository
- edit `config/runtime_paths.yaml` for your system:
  - set `results_root`
  - set `data.named_roots.default` if you want relative `--data` paths to resolve automatically
  - optionally set extra `data.named_roots.<name>` entries and pass `--data-root-key <name>` when different dataset families live under different directories
  - set `bayeseor.repo_path` to your local BayesEoR clone
  - set `bayeseor.conda_sh` and `bayeseor.conda_env`
  - set CPU and GPU SLURM defaults for your site
- obtain or generate the UVH5 dataset you want to analyse
- if you are using one of the example commands below, replace the example `--data` value with a dataset path that actually exists on your system

If you are unsure which command to start with, run:

```bash
valska-bayeseor-help
```

If you want copy/paste command sequences rather than a command map, jump to
[Detailed examples](#detailed-examples).

### CLI quick reference

#### Setup And Submission

| Command | Purpose | Detailed docs |
|---|---|---|
| `valska-bayeseor-help` | Print command index and common workflows | [operations: command index](./bayeseor_operations.md#0-command-index--discoverability) |
| `valska-bayeseor-prepare` | Prepare one run directory and artefacts | [valska-bayeseor-prepare](#valska-bayeseor-prepare) |
| `valska-bayeseor-sweep` | Prepare and/or submit sweep points | [valska-bayeseor-sweep](#valska-bayeseor-sweep) |
| `valska-bayeseor-submit` | Submit CPU/GPU stages for one prepared run | [valska-bayeseor-submit --stage cpu](#valska-bayeseor-submit---stage-cpu), [valska-bayeseor-submit --stage gpu](#valska-bayeseor-submit---stage-gpu) |

#### Reporting And Health

| Command | Purpose | Detailed docs |
|---|---|---|
| `valska-bayeseor-report` | Generate report tables/plots for one sweep | [reporting: CLI usage](./bayeseor_reporting.md#cli-usage) |
| `valska-bayeseor-list-sweeps` | Discover available sweep directories | [reporting: wrapper script usage](./bayeseor_reporting.md#wrapper-script-usage) |
| `valska-bayeseor-sweep-status` | Inspect per-point completeness for one sweep | [reporting: sweep health helpers](./bayeseor_reporting.md#sweep-health-helpers) |
| `valska-bayeseor-validate-sweep` | Validate sweep integrity with exit-code semantics | [reporting: sweep health helpers](./bayeseor_reporting.md#sweep-health-helpers) |
| `valska-bayeseor-sweep-audit` | Aggregate discovery + status + validation | [reporting: sweep health helpers](./bayeseor_reporting.md#sweep-health-helpers) |

#### Operations

| Command | Purpose | Detailed docs |
|---|---|---|
| `valska-bayeseor-resume` | Generate exact submit commands for incomplete points | [operations: resume incomplete sweep points](./bayeseor_operations.md#1-resume-incomplete-sweep-points) |
| `valska-bayeseor-report-all` | Batch-generate reports across discovered sweeps | [operations: batch reporting](./bayeseor_operations.md#2-batch-reporting-across-discovered-sweeps) |
| `valska-bayeseor-compare-sweeps` | Compare metrics between two sweep summaries | [operations: compare two sweep outcomes](./bayeseor_operations.md#3-compare-two-sweep-outcomes) |
| `valska-bayeseor-cleanup` | Safe cleanup workflow (dry-run by default) | [operations: cleanup](./bayeseor_operations.md#4-cleanup-safe-by-default-maintenance) |

### Quick Definitions

- a single point is one prepared run directory for one perturbation value
- a sweep is a collection of single-point runs across multiple perturbation values

### Which command should I use?

- Need a quick command map before you start? → `valska-bayeseor-help`
- Need to create run inputs/scripts for one single-point run? → `valska-bayeseor-prepare`
- Need to submit stages for one prepared run dir? → `valska-bayeseor-submit`
- Need to prepare/submit a sweep across multiple perturbation values? → `valska-bayeseor-sweep`
- Need to inspect one sweep health quickly? → `valska-bayeseor-sweep-status`
- Need pass/fail validation semantics for one sweep? → `valska-bayeseor-validate-sweep`
- Need campaign-wide health and validation overview? → `valska-bayeseor-sweep-audit`
- Need restart suggestions for incomplete points? → `valska-bayeseor-resume`
- Need reports for one sweep? → `valska-bayeseor-report`
- Need reports for many sweeps? → `valska-bayeseor-report-all`
- Need side-by-side metric comparison between two sweeps? → `valska-bayeseor-compare-sweeps`
- Need maintenance cleanup (dry-run first)? → `valska-bayeseor-cleanup`

For command-local examples of helper CLIs, run each command with `--help`.

Public documentation note:
- do not put personal filesystem paths into your committed `runtime_paths.yaml`
- replace all example paths with paths that are valid for your own system or site

Replace:
- `achromatic_Gaussian` with a beam-model label matching the data you are analysing
- `GLEAM` with a sky-model label matching the data you are analysing
- `...uvh5` with your dataset
- `RUN_ID` / `SWEEP_ID` with something meaningful

### valska-bayeseor-help

If you want the shortest possible command map before you start:

```bash
valska-bayeseor-help
```

For topic-specific help:

```bash
valska-bayeseor-help --topic setup
valska-bayeseor-help --topic submission
valska-bayeseor-help --topic reporting
```

### valska-bayeseor-prepare

What this command does:

- creates a run directory containing:
- BayesEoR config YAML(s)
- SLURM submit scripts for CPU and GPU stages
- a manifest recording provenance and resolved paths

Dry-run example:

```bash
valska-bayeseor-prepare \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id RUN_ID \
  --fwhm-perturb-frac 0.01 \
  --dry-run
```

To create the files for real, run the same command without `--dry-run`.

### valska-bayeseor-sweep

A sweep prepares N run dirs (one per FWHM perturbation) and can optionally submit CPU/GPU stages
across all points.

Prepare only (no submission):

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id SWEEP_ID \
  --fwhm-fracs 0.01 0.0 \
  --submit none
```

For a first end-to-end run on a new system, prefer a single submission command:

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id SWEEP_ID \
  --fwhm-fracs 0.01 0.0 \
  --submit all
```

This is the most reliable path because ValSKA submits CPU and GPU together per point
and manages the dependency chain in one invocation.

If you want finer control, you can split the stages:

Submit CPU stage across all points:

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id SWEEP_ID \
  --fwhm-fracs 0.01 0.0 \
  --submit cpu
```

Submit GPU stage across all points later (advanced / recovery workflow):

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id SWEEP_ID \
  --fwhm-fracs 0.01 0.0 \
  --submit gpu
```

If you use the split CPU/GPU path, make sure:

- your CPU stage has already produced the required precompute outputs
- `jobs.json` exists for each point if you expect ValSKA to reuse recorded CPU job ids
- your site-specific SLURM defaults in `runtime_paths.yaml` are correct before submission

Dry-run submission (show `sbatch` commands but do not submit):

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id SWEEP_ID \
  --fwhm-fracs 0.01 0.0 \
  --submit cpu \
  --submit-dry-run
```

### valska-bayeseor-submit --stage cpu

If you are using the submit CLI:

```bash
valska-bayeseor-submit /path/to/run_dir --stage cpu
```

Or manually (inside the run_dir output from prepare):

```bash
sbatch /path/to/run_dir/submit_cpu_precompute.sh
```

### valska-bayeseor-submit --stage gpu

Use this mode when you already have a prepared run directory and you want to
launch GPU work separately from CPU precompute.

Important:

- this split CPU-then-GPU workflow is useful for recovery and explicit control
- on some SLURM sites, later GPU submission can be sensitive to how CPU job
  dependencies are handled
- for a first end-to-end run, `valska-bayeseor-sweep --submit all` is usually
  the safest path

Using the submit CLI:

```bash
valska-bayeseor-submit /path/to/run_dir --stage gpu
```

Or manually:

```bash
sbatch --dependency=afterok:<CPU_JOBID> /path/to/run_dir/submit_signal_fit_gpu_run.sh
sbatch --dependency=afterok:<CPU_JOBID> /path/to/run_dir/submit_no_signal_gpu_run.sh
```

---

## Concepts

### Beam / sky taxonomy (directory layout)

We organise results by the two “observation-defining” axes:

- `beam_model`: instrument / beam model label (e.g. `achromatic_Gaussian`, `chromatic_Gaussian`, `airy`)
- `sky_model`: sky model label (e.g. `GLEAM`, `GSM`, `GLEAM_plus_GSM`)

This keeps campaigns predictable when you explore multiple sky models and multiple beam models.

### Template + variant concept (collision-free template differences)

Many BayesEoR runs differ only by template-level settings (chromatic vs achromatic, alternate priors, etc).
To avoid collisions, we include a `<variant>` directory level.

- If you do not specify `--variant`, it is derived from the template filename stem by removing the first `_template`.

Examples:
- `validation_v1d0_template.yaml`            → `validation_v1d0`
- `validation_v1d0_template_achromatic.yaml` → `validation_v1d0_achromatic`
- `validation_achromatic_Gaussian.yaml`      → `validation_achromatic_Gaussian`

You can override the auto-derived value with `--variant`.

### What gets created where

Canonical single-run directory:

```text
<results_root>/bayeseor/<beam_model>/<sky_model>/<variant>/<run_label>/<run_id>[/<UTCSTAMP>]
```

Canonical sweep root and points:

```text
<results_root>/bayeseor/<beam_model>/<sky_model>/_sweeps/<sweep_id>/<variant>/<run_label>[/<UTCSTAMP>]
```

Notes:
- `<run_label>` is typically `fwhm_<value>` (e.g. `fwhm_1.0e-02`) and is auto-generated from FWHM frac.
- `--unique` appends a UTC timestamp suffix (useful for one-off runs; usually not recommended for resumable sweeps).

---

## Lifecycle diagram

This is the “mental model” for the typical workflow.

```text
+---------------------------+
| Choose beam + sky + data  |
| Choose template (optional)|
+-------------+-------------+
              |
              v
+---------------------------+
| PREPARE (per run)         |
| valska-bayeseor-prepare   |
| - writes run_dir          |
| - config_*.yaml           |
| - submit_*.sh             |
| - manifest.json           |
+-------------+-------------+
              |
              v
+---------------------------+
| CPU stage (precompute)    |
| valska-bayeseor-submit    |
|   --stage cpu             |
| or sbatch submit_cpu*.sh  |
| - records CPU job id      |
|   into jobs.json          |
+-------------+-------------+
              |
              v
+---------------------------+
| GPU stage (run analyses)  |
| valska-bayeseor-submit    |
|   --stage gpu             |
| - uses afterok:<CPU_JOBID>|
| - submits signal/no-signal|
| - records GPU job ids     |
+---------------------------+
```

Sweeps are a thin wrapper that repeats PREPARE across multiple FWHM fractions.

Recommended first run:

```bash
valska-bayeseor-sweep --submit all    (submit CPU+GPU in one go per point)
```

Other modes for setup checks, recovery, or tighter stage-by-stage control:

```bash
valska-bayeseor-sweep --submit none   (prepare all points)
valska-bayeseor-sweep --submit cpu    (submit CPU across points)
valska-bayeseor-sweep --submit gpu    (submit GPU across points; reuses completed CPU outputs or CPU job ids)
```

---

## Detailed examples

The examples below are intentionally explicit, and many include abridged output snippets.

### A) Prepare (dry-run)

```bash
valska-bayeseor-prepare \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id test_prepare1 \
  --fwhm-perturb-frac 0.01 \
  --dry-run
```

Example output (abridged):

```text
[DRY RUN] Prepare would be executed with:
  results_root:       /share/.../validation_results/UKSRC
  beam_model:         achromatic_Gaussian
  sky_model:          GLEAM
  run_id:             test_prepare1
  run_label:          fwhm_1.0e-02
  template:           .../templates/validation_achromatic_Gaussian.yaml
  variant:            validation_achromatic_Gaussian
  data:               /share/.../gsm_plus_gleam...uvh5
  run_dir (preview):  /share/.../bayeseor/achromatic_Gaussian/GLEAM/validation_achromatic_Gaussian/fwhm_1.0e-02/test_prepare1
  ...
[DRY RUN] No files will be created.
```

### B) Prepare (real)

```bash
valska-bayeseor-prepare \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id test_prepare1 \
  --fwhm-perturb-frac 0.01
```

Example output (abridged):

```text
Run prepared:
  run_dir:      /share/.../bayeseor/achromatic_Gaussian/GLEAM/validation_achromatic_Gaussian/fwhm_1.0e-02/test_prepare1
  manifest:     /share/.../manifest.json
  beam_model:   achromatic_Gaussian
  sky_model:    GLEAM
  variant:      validation_achromatic_Gaussian
  run_label:    fwhm_1.0e-02
  run_id:       test_prepare1

Next steps:
  Option A) Submit via ValSKA (recommended):
    valska-bayeseor-submit /share/.../test_prepare1 --stage cpu
    valska-bayeseor-submit /share/.../test_prepare1 --stage gpu
  Option B) Manual submission:
    sbatch /share/.../submit_cpu_precompute.sh
    sbatch /share/.../submit_signal_fit_gpu_run.sh
    sbatch /share/.../submit_no_signal_gpu_run.sh
```

### C) Sweep (dry-run with point directories)

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id sweep_test2 \
  --fwhm-fracs 0.01 0.0 \
  --dry-run
```

Example output (abridged):

```text
[DRY RUN] Sweep would be executed with:
  sweep_dir: /share/.../bayeseor/achromatic_Gaussian/GLEAM/_sweeps/sweep_test2
  variant:   validation_achromatic_Gaussian
  ...

[DRY RUN] Points:
  +0.010  fwhm_1.0e-02  ->  /share/.../_sweeps/sweep_test2/validation_achromatic_Gaussian/fwhm_1.0e-02
  +0.000  fwhm_0.0e+00  ->  /share/.../_sweeps/sweep_test2/validation_achromatic_Gaussian/fwhm_0.0e+00
```

### D) Sweep (prepare only)

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id sweep_test2 \
  --fwhm-fracs 0.01 0.0 \
  --submit none
```

This writes:
- sweep manifest: `.../_sweeps/<sweep_id>/sweep_manifest.json`
- per-point run dirs containing `manifest.json`, configs, and SLURM scripts

### E) Submit CPU+GPU together (fresh sweep)

If you want the most reliable first end-to-end run, use:

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id sweep_test2 \
  --fwhm-fracs 0.01 0.0 \
  --submit all
```

This is the recommended first-run path because ValSKA submits CPU and GPU together per point
and manages the dependency chain in one invocation.

### F) Submit CPU across sweep points

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id sweep_test2 \
  --fwhm-fracs 0.01 0.0 \
  --submit cpu
```

Typical output includes a “Submission summary” listing the sbatch calls per point.
It should also record job ids into each point’s `jobs.json` (real submit).

To preview the sbatch commands without submitting:

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id sweep_test2 \
  --fwhm-fracs 0.01 0.0 \
  --submit cpu \
  --submit-dry-run
```

### G) Submit GPU across sweep points (after CPU)

GPU-only submission works when each point either:
- has completed CPU precompute outputs already present, or
- has a dependency job id available (typically from that point’s `jobs.json`)

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id sweep_test2 \
  --fwhm-fracs 0.01 0.0 \
  --submit gpu
```

If you attempt GPU submission before CPU job ids exist, ValSKA should report an error explaining
you must either:
- submit CPU in the same invocation (`--submit all`), or
- pass `--depend-afterok <JOBID>` (advanced), or
- ensure `jobs.json` exists with a recorded CPU job id, or
- wait for CPU precompute to finish so the required matrix stack exists under the run directory

Dry-run GPU submission (show commands, no jobs submitted):

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id sweep_test2 \
  --fwhm-fracs 0.01 0.0 \
  --submit gpu \
  --submit-dry-run
```

Example output (abridged; dependency read from jobs.json):

```bash
sbatch --dependency=afterok:<CPU_JOBID> .../submit_signal_fit_gpu_run.sh
sbatch --dependency=afterok:<CPU_JOBID> .../submit_no_signal_gpu_run.sh
```

### H) Slurm array submission for sweep campaigns

By default, `valska-bayeseor-sweep` submits one CPU job and one or two GPU jobs
per sweep point. This per-point submission mode is useful for debugging, but it
can create many scheduler jobs for a full campaign.

Use Slurm array mode when you want the same sweep represented by one CPU array
job plus one or two GPU array jobs:

```bash
--submit-mode array
```

The array-mode concurrency limits are controlled independently for CPU and GPU
tasks:

```bash
--array-max-cpu 4
--array-max-gpu 2
```

For example, a sweep with 11 perturbation points and `--array-max-gpu 2`
generates GPU array scripts containing:

```text
#SBATCH --array=0-10%2
```

This means Slurm can run at most two GPU array tasks from that array at once.
Choose these limits according to the allocation and usage policy of the cluster
being used.

Before submitting real jobs on a new cluster, run a submit dry-run into a
scratch or test output root:

```bash
RUN_ID="sweep_v3_array_smoke_$(date -u +%Y%m%dT%H%M%SZ)"
RESULTS_ROOT="/path/to/scratch/valska-array-smoke-${RUN_ID}"

case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-achromatic_Gaussian-GSM_v3.sh \
  --run-id "$RUN_ID" \
  --results-root "$RESULTS_ROOT" \
  --submit all \
  --submit-mode array \
  --array-max-cpu 4 \
  --array-max-gpu 2 \
  --submit-dry-run
```

`--submit-dry-run` prepares the sweep directory, writes the Slurm array scripts,
prints the `sbatch` commands, and records dry-run metadata without submitting
jobs. The output should report:

```text
submit:              all (ok)
submit_mode:         array
job_id(cpu_precompute_array): DRY_RUN_CPU_ARRAY_JOB_ID
dependency(gpu_array): afterok:DRY_RUN_CPU_ARRAY_JOB_ID
```

Inspect the generated artefacts before the real submission:

```bash
find "$RESULTS_ROOT" \
  -name jobs.json \
  -o -name array_tasks.json \
  -o -name 'submit_*_array.sh'

grep -R "#SBATCH --array" "$RESULTS_ROOT"
grep -R "afterok:DRY_RUN_CPU_ARRAY_JOB_ID" "$RESULTS_ROOT"
```

The sweep-level array files are written under:

```text
<results_root>/bayeseor/<beam>/<sky>/_sweeps/<run_id>/
```

Important files include:

- `array_tasks.json`: maps Slurm array indices to per-point run directories and
  config files
- `submit_cpu_precompute_array.sh`: CPU precompute array script
- `submit_signal_fit_gpu_array.sh`: signal-fit GPU array script
- `submit_no_signal_gpu_array.sh`: no-signal GPU array script
- `jobs.json`: sweep-level submission record containing array job IDs,
  dependencies, commands, and dry-run placeholders when applicable

If the dry-run output looks correct, submit the same sweep for real by
removing `--submit-dry-run`:

```bash
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-achromatic_Gaussian-GSM_v3.sh \
  --run-id "$RUN_ID" \
  --results-root "$RESULTS_ROOT" \
  --submit all \
  --submit-mode array \
  --array-max-cpu 4 \
  --array-max-gpu 2
```

In real array submission mode, ValSKA submits the CPU array first, records its
Slurm job ID in sweep-level `jobs.json`, then submits the GPU array job(s) with:

```text
--dependency=afterok:<cpu_array_job_id>
```

To split submission into two steps, submit CPU first:

```bash
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-achromatic_Gaussian-GSM_v3.sh \
  --run-id "$RUN_ID" \
  --results-root "$RESULTS_ROOT" \
  --submit cpu \
  --submit-mode array \
  --array-max-cpu 4 \
  --array-max-gpu 2
```

Then submit GPU arrays after the CPU array job has been recorded:

```bash
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-achromatic_Gaussian-GSM_v3.sh \
  --run-id "$RUN_ID" \
  --results-root "$RESULTS_ROOT" \
  --submit gpu \
  --submit-mode array \
  --array-max-cpu 4 \
  --array-max-gpu 2
```

Alternatively, pass an explicit CPU dependency if the CPU array job was
submitted outside the current `jobs.json` record:

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GSM \
  --data-root-key gaussian \
  --data gsm-nside256-158.3-167.1MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id "$RUN_ID" \
  --results-root "$RESULTS_ROOT" \
  --template validation_achromatic_Gaussian.yaml \
  --submit gpu \
  --submit-mode array \
  --array-max-gpu 2 \
  --depend-afterok <CPU_ARRAY_JOB_ID>
```

Array submission changes how jobs are grouped in Slurm; it does not change the
per-point output layout. Each perturbation point still has its own run
directory beneath the sweep directory, so the same reporting and sweep-health
commands can be used after the jobs complete.

### I) Advanced: per-point submission with valska-bayeseor-submit

Sometimes you only want to submit a subset of points or a single point, especially when testing.

Example: submit GPU for just one perturbation fraction (assuming CPU already submitted and recorded):

```bash
valska-bayeseor-sweep \
  --beam achromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5 \
  --run-id sweep_test2 \
  --fwhm-fracs 0.01 \
  --submit gpu
```

Or, if you know the run_dir explicitly:

```bash
valska-bayeseor-submit /share/.../_sweeps/sweep_test2/validation_achromatic_Gaussian/fwhm_1.0e-02 --stage gpu
```

### J) Monitoring jobs
Common SLURM checks:

```bash
squeue -u $USER
sacct -j <JOBID> --format=JobID,JobName,State,Elapsed,ExitCode
tail -n 200 /path/to/run_dir/slurm-<JOBID>.out
```

ValSKA also records submission information into:
- per-point `jobs.json`
- sweep-level `sweep_manifest.json` (including submit results)

### K) Post-processing reports (tables + plots)

After sweep jobs complete (or partially complete), generate report artefacts with:

```bash
valska-bayeseor-report /path/to/_sweeps/<run_id>
```

To include extended outputs (`plot_analysis_results` and `run_complete_bayeseor_analysis` table/json):

```bash
valska-bayeseor-report /path/to/_sweeps/<run_id> \
  --include-plot-analysis-results \
  --include-complete-analysis-table
```

To print the complete-analysis terminal table while also writing its JSON and
CSV artefacts:

    valska-bayeseor-report /path/to/_sweeps/<run_id> \
      --print-complete-analysis-table

This option implies `--include-complete-analysis-table`. Use
`--complete-analysis-table-style plain` for ASCII-only validation labels and
`--color never` for uncoloured terminal output. It cannot be combined with
`--json`; use `--include-complete-analysis-table --json` for a
machine-readable report payload.

Wrapper equivalent (extended outputs enabled by default):

```bash
bash_scripts/valska-bayeseor-report-sweep.sh --sweep-dir /path/to/_sweeps/<run_id>
```

Airy helper convenience (prepare/submit sweep and auto-run reporting at the end):

```bash
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-airy_diam14m-GSM_plus_GLEAM_v3.sh --submit all --report
```

Skip plot generation when auto-reporting:

```bash
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-airy_diam14m-GSM_plus_GLEAM_v3.sh --submit all --report-no-plots
```

For full reporting options and failure-handling behaviour, see:

- [BayesEoR reporting workflows](./bayeseor_reporting.md)

### L) Sweep health/status checks

Inspect a sweep and summarise point completeness:

```bash
valska-bayeseor-sweep-status /path/to/_sweeps/SWEEP_ID
```

JSON mode (scripting/automation):

```bash
valska-bayeseor-sweep-status /path/to/_sweeps/SWEEP_ID --json
```

Validate and fail non-zero for incomplete sweeps:

```bash
valska-bayeseor-validate-sweep /path/to/_sweeps/SWEEP_ID
```

If partial completion is acceptable:

```bash
valska-bayeseor-validate-sweep /path/to/_sweeps/SWEEP_ID --allow-partial
```

If you also require `jobs.json` per point:

```bash
valska-bayeseor-validate-sweep /path/to/_sweeps/SWEEP_ID --require-jobs-json
```

### M) Aggregate sweep audit

Run one command that discovers sweeps and evaluates status + validation:

```bash
valska-bayeseor-sweep-audit
```

Apply filters and output JSON:

```bash
valska-bayeseor-sweep-audit --beam airy_diam14m --sky GSM_plus_GLEAM --json
```

Use non-zero exit if any audited sweep is invalid:

```bash
valska-bayeseor-sweep-audit --fail-on-invalid
```

### N) Backwards compatibility: deprecated --scenario

Older scripts used `--scenario` as a single label that mixed multiple concepts.

ValSKA now prefers `--beam` and `--sky` explicitly.

If you must use `--scenario`, it is deprecated and must be unambiguous:

```bash
--scenario <beam>/<sky>
--scenario <beam>__<sky>
```

Examples:

```bash
valska-bayeseor-sweep \
  --scenario achromatic_Gaussian/GLEAM \
  --data ...uvh5 \
  --run-id sweep_oldstyle \
  --fwhm-fracs 0.01 0.0 \
  --submit none
```

Ambiguous older patterns like `GLEAM_beam` are rejected to prevent silent misrouting.

---

## Notes for UKSRC users

- Keep beam/sky labels stable across campaigns. Your analysis notebooks, plots, and archiving will thank you.
- Prefer `--submit-dry-run` before real submissions when testing new templates or SLURM settings.
- For large sweeps, consider committing a standard `bayeseor.sweep.fwhm_fracs` set in runtime_paths.yaml
  and only override with `--fwhm-fracs` for special experiments.
- If you run into walltime, MultiNest is typically resumable; ValSKA supports resubmission patterns
  (see `--resubmit` in your CLI help).

---

## Related files (in this repo)

- `src/valska/external_tools/bayeseor/cli_prepare.py`
- `src/valska/external_tools/bayeseor/cli_sweep.py`
- `src/valska/external_tools/bayeseor/cli_submit.py`
- `src/valska/external_tools/bayeseor/setup.py`
- `src/valska/external_tools/bayeseor/sweep.py`
- `src/valska/external_tools/bayeseor/submit.py`
- `config/runtime_paths.yaml`
- `case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-airy_diam14m-GSM_plus_GLEAM_v3.sh`
