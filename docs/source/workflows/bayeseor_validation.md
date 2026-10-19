# BayesEoR validation workflow (ValSKA)

This document describes the **BayesEoR validation workflow** implemented in
`ValSKA`, with an emphasis on reproducibility, resumability, and
high-performance computing (HPC) best practices.

It is intended to complement the project README by providing additional
context, rationale, and operational detail.

---

## Design goals

Naming conventions used in this page:

- `run_id`: user-chosen identifier for one prepared run or sweep campaign
- `sweep_id`: commonly used synonym for a sweep-level `run_id`
- `run_dir`: a single prepared point directory
- `sweep_dir`: the `_sweeps/<run_id>` root containing `sweep_manifest.json`

The BayesEoR workflow in ValSKA is designed to satisfy the following principles:

- **Reproducibility**
  Every run is fully specified by explicit configuration files and provenance
  metadata.

- **Inspectability**
  Users should be able to examine exactly what will be run *before* submitting
  jobs to a scheduler.

- **Resumability**
  Long-running Bayesian inference (e.g. MultiNest) must be easy to resume after
  walltime or preemption.

- **HPC appropriateness**
  The workflow should integrate cleanly with batch schedulers (SLURM), avoid
  hidden state, and respect site policies.

To achieve this, ValSKA enforces a strict separation between **preparation**
and **submission**.

---

## Prepare vs submit: separation of concerns

### Prepare phase

The *prepare* phase is performed using:

```bash
valska-bayeseor-prepare
```

This phase:

- renders BayesEoR configuration YAML files from templates
- writes SLURM submit scripts for each execution stage
- creates a structured run directory under the ValSKA results root
- writes a `manifest.json` capturing full provenance

Critically, the prepare phase:

- does **not** execute BayesEoR
- does **not** submit jobs
- does **not** modify any global state

The output of this phase is a **self-contained run directory** that can be:
- inspected
- versioned
- archived
- copied to another system
- reused for resubmission

---

### Submit phase

The *submit* phase is performed using:

```bash
valska-bayeseor-submit <run_dir>
```

This phase:

- reads an existing prepared run directory
- submits SLURM jobs using the generated scripts
- enforces job dependencies explicitly
- records submitted job IDs in `jobs.json`

Submission is intentionally lightweight: it orchestrates `sbatch` calls but
does not attempt to manage or monitor running jobs.

---

## Run directory structure

A typical prepared run directory has the form:

```text
<results_root>/bayeseor/<beam_model>/<sky_model>/<variant>/<run_label>/<run_id>/
```

or, if `--unique` is used:

```text
<results_root>/bayeseor/<beam_model>/<sky_model>/<variant>/<run_label>/<run_id>/<timestamp>/
```

For sweep campaigns, point run directories are created under:

```text
<results_root>/bayeseor/<beam_model>/<sky_model>/_sweeps/<run_id>/<variant>/<run_label>/
```

Inside this directory you will typically find:

- `config_signal_fit.yaml`
- `config_no_signal.yaml`
- `submit_cpu_precompute.sh`
- `submit_signal_fit_gpu_run.sh`
- `submit_no_signal_gpu_run.sh`
- `manifest.json`
- (after submission) `jobs.json`

This directory is the **unit of reproducibility** in ValSKA.

---

## Execution stages and dependencies

BayesEoR runs are structured as two stages:

### 1. CPU precompute stage

- Computes instrument transfer matrices and related quantities
- Shared across signal and no-signal hypotheses
- Typically CPU-bound

Submitted via:

```bash
submit_cpu_precompute.sh
```

### 2. GPU inference stages

- One job per hypothesis (e.g. `signal_fit`, `no_signal`)
- Runs BayesEoR with `--gpu --run`
- Typically long-running and GPU-bound

Submitted via:

```bash
submit_<hyp>_gpu_run.sh
```

GPU jobs depend explicitly on the successful completion of the CPU stage
using SLURM `afterok` dependencies.

---

## Provenance and state tracking

### manifest.json

Written at *prepare time*.

Contains:
- template name or path
- BayesEoR repository path
- runtime configuration
- SLURM parameters
- applied overrides (e.g. FWHM perturbations)
- paths to all generated artefacts

This file represents **what was intended to be run**.

It is treated as immutable.

---

### jobs.json

Written at *submit time*.

Contains:
- SLURM job IDs
- submission timestamps
- dependency structure
- exact `sbatch` commands used

This file represents **what was actually submitted**.

If resubmission is required, previous versions of this file may be archived
(e.g. `jobs_YYYYMMDDTHHMMSSZ.json`) to preserve history.

---

## Resubmission and walltime handling

BayesEoR uses MultiNest, which can resume from existing output directories.

If a job hits walltime:

- output files remain in the run directory
- no configuration regeneration is required

To requeue cleanly:

```bash
valska-bayeseor-submit <run_dir> --stage gpu --resubmit
```

This will:
- archive the existing `jobs.json`
- submit new GPU jobs
- reuse existing BayesEoR outputs

This pattern avoids accidental double submission while making recovery trivial.

---

## Manual submission remains supported

At all times, users may bypass ValSKA-managed submission and run:

```bash
sbatch submit_cpu_precompute.sh
sbatch submit_signal_fit_gpu_run.sh
sbatch submit_no_signal_gpu_run.sh
```

ValSKA does not hide or replace native scheduler behaviour.

---

## When to use --unique vs stable run directories

- Use **stable run directories** (default) when:
  - you want to resume runs
  - you expect walltime interruptions
  - you are iterating on the same configuration

- Use **--unique** when:
  - performing parameter sweeps
  - launching many independent realisations
  - archival separation is preferred over resumability

Both modes are fully supported by the workflow.

---

## Summary

The ValSKA BayesEoR workflow emphasises:

- explicit artefact generation
- transparent submission
- reproducible directory structures
- safe and convenient resubmission

This structure is intentional and designed to scale to both
validation studies and production inference runs on shared HPC systems.
