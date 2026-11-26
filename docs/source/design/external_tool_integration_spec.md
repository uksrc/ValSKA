# External Tool Integration Specification

**Version:** 1.0.0
**Status:** Released
**Last updated:** 2026-01-25

---

## 1. Introduction

### 1.1 Purpose

This specification defines the contract that external tool integrations must satisfy to be compatible with the ValSKA framework. It establishes consistent patterns for:

- CLI entry points
- Run directory structure
- Provenance tracking
- SLURM job submission
- Configuration management
- Resumability

### 1.2 Scope

This specification covers **required** behaviours for all external tools, plus **optional** extension patterns (e.g., sweeps) that tools may implement if appropriate.

It does not prescribe internal implementation details — tools may organise their code as appropriate, provided they satisfy the external contract defined here.

Note that tool integrations may use the shared infrastructure located under `valska.external_tools.common` but should preserve the externally visible behaviour defined by this specification.

### 1.3 Definitions

| Term | Definition |
|------|------------|
| **Tool** | An external scientific application integrated with ValSKA (e.g., BayesEoR, pyuvsim) |
| **Run directory** | A self-contained directory holding all artefacts for a single execution |
| **Stage** | A discrete unit of work within a tool's execution (e.g., CPU precompute, GPU inference) |
| **Prepare** | Generate run artefacts without executing or submitting jobs |
| **Submit** | Submit previously prepared artefacts to SLURM |
| **Runner** | Abstraction for how a tool is executed (e.g., conda environment, container) |

### 1.4 Design principles

External tool integrations in ValSKA adhere to these principles:

1. **Reproducibility** — Every run is fully specified by explicit configuration and provenance metadata
2. **Inspectability** — Users can examine exactly what will run before submission
3. **Resumability** — Long-running jobs can be resumed after interruption
4. **HPC appropriateness** — Integrations respect batch scheduler semantics and avoid hidden state
5. **Separation of concerns** — Preparation and submission are distinct, auditable phases

---

## 2. CLI entry points

### 2.1 Naming convention

Each tool **must** provide CLI entry points following this naming pattern:

```
valska-<tool>-prepare
valska-<tool>-submit
```

Where `<tool>` is a lowercase identifier using underscores for word separation (e.g., `bayeseor`, `pyuvsim`).

**Examples:**
- `valska-bayeseor-prepare`, `valska-bayeseor-submit`
- `valska-pyuvsim-prepare`, `valska-pyuvsim-submit`

### 2.2 Optional entry points

Tools **may** provide additional entry points for extended functionality:

| Entry point | Purpose |
|-------------|---------|
| `valska-<tool>-sweep` | Orchestrate multiple runs across a parameter space |
| `valska-<tool>-status` | Query status of submitted jobs |
| `valska-<tool>-collect` | Gather results from completed runs |

These are optional and tool-specific.

### 2.3 Registration

Entry points **must** be registered in `pyproject.toml`:

```toml
[project.scripts]
valska-pyuvsim-prepare = "valska.external_tools.pyuvsim.cli_prepare:main"
valska-pyuvsim-submit = "valska.external_tools.pyuvsim.cli_submit:main"
```

---

## 3. Prepare phase

### 3.1 Purpose

The prepare phase generates all artefacts required for execution without actually running the tool or submitting jobs.

### 3.2 Required behaviours

The prepare CLI **must**:

1. Accept configuration via CLI arguments and/or configuration files
2. Resolve runtime paths using the configuration hierarchy (see §7)
3. Create a run directory containing all execution artefacts
4. Write a `manifest.json` file capturing full provenance
5. Generate SLURM submit scripts for each execution stage
6. Support `--dry-run` to preview actions without writing files

The prepare CLI **must not**:

1. Execute the external tool
2. Submit jobs to SLURM
3. Modify any state outside the run directory
4. Depend on network resources (beyond filesystem access)

### 3.3 Required arguments

All prepare CLIs **must** support these arguments:

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `--dry-run` | flag | no | Preview actions without creating files |
| `--results-root` | path | no | Override results root directory |

Additional arguments are tool-specific.

### 3.4 Dry-run semantics

When `--dry-run` is specified:

1. Print resolved configuration and paths to stdout
2. Print the run directory path that would be created
3. Print SLURM configuration that would be applied
4. Exit with code 0
5. Create no files or directories

**Example output format:**

```
[DRY RUN] Prepare would be executed with:
  results_root:       /path/to/results [runtime_paths.yaml]
  run_id:             test_001
  run_dir (preview):  /path/to/results/pyuvsim/run_001/
  ...

[DRY RUN] No files will be created.
```

### 3.5 Output

On successful completion, the prepare CLI **should**:

1. Print the created run directory path
2. Print the manifest path
3. Print suggested next steps (submit commands)
4. Exit with code 0

---

## 4. Submit phase

### 4.1 Purpose

The submit phase submits previously prepared artefacts to SLURM for execution.

### 4.2 Required behaviours

The submit CLI **must**:

1. Accept a run directory path as the primary argument
2. Validate that the run directory contains required artefacts
3. Submit SLURM jobs using the generated submit scripts
4. Handle inter-stage dependencies correctly
5. Write a `jobs.json` file recording submission details
6. Support `--dry-run` to preview submission without executing

The submit CLI **must not**:

1. Modify configuration files in the run directory
2. Regenerate submit scripts
3. Monitor or wait for job completion

### 4.3 Required arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `<run_dir>` | path | yes | Path to prepared run directory |
| `--dry-run` | flag | no | Preview submission without executing |
| `--stage` | string | no | Submit only specified stage(s) |
| `--resubmit` | flag | no | Allow resubmission (archive existing jobs.json) |

### 4.4 Stage selection

If a tool has multiple stages, the submit CLI **must** support:

- `--stage <name>` — Submit only the named stage
- `--stage all` — Submit all stages with correct dependencies (default)

Stage names are tool-specific.

### 4.5 Dependency handling

When submitting multiple stages:

1. Submit stages in dependency order
2. Use SLURM `--dependency=afterok:<jobid>` for dependent stages
3. Record the dependency structure in `jobs.json`

### 4.6 Resubmission

When `--resubmit` is specified:

1. Archive the existing `jobs.json` to `jobs_<timestamp>.json`
2. Submit new jobs
3. Write a fresh `jobs.json`

This supports recovery from walltime limits without manual cleanup.

---

## 5. Run directory structure

### 5.1 Location

Run directories **must** be created under:

```
<results_root>/<tool>/<taxonomy>/<run_id>/
```

Where:
- `<results_root>` is the configured results root
- `<tool>` is the tool identifier (e.g., `bayeseor`, `pyuvsim`)
- `<taxonomy>` is a tool-specific hierarchy (e.g., `<beam_model>/<sky_model>/<variant>`)
- `<run_id>` is the user-provided run identifier

Tools **may** support a `--unique` flag to append a UTC timestamp for uniqueness:

```
<results_root>/<tool>/<taxonomy>/<run_id>/<YYYYMMDDTHHMMSSZ>/
```

### 5.2 Required contents

Every run directory **must** contain:

| File | Created by | Description |
|------|------------|-------------|
| `manifest.json` | prepare | Provenance and configuration record |
| `submit_<stage>.sh` | prepare | SLURM submit script(s), one per stage |

After submission:

| File | Created by | Description |
|------|------------|-------------|
| `jobs.json` | submit | Submission record with job IDs |

### 5.3 Tool-specific contents

Tools **may** include additional files as needed:

- Configuration files for the external tool
- Input data symlinks or references
- Stage-specific output directories

### 5.4 Immutability

The following files **must not** be modified after creation:

- `manifest.json`
- `submit_*.sh` scripts

The `jobs.json` file **may** be replaced on resubmission (with archival of the previous version).

---

## 6. Provenance files

### 6.1 manifest.json

#### 6.1.1 Purpose

Records the complete specification of a prepared run, capturing everything needed to understand and reproduce it.

#### 6.1.2 Schema

```json
{
  "tool": "bayeseor",
  "created_utc": "2025-01-15T12:34:56Z",
  "valska_version": "0.1.0",
  "run_id": "fwhm_sweep_001",
  "run_dir": "/abs/path/to/run_dir",
  "results_root": "/abs/path/to/results_root",
  "template_yaml": "/abs/path/to/template.yaml",
  "template_name": "validation_v1d0_template.yaml",
  "data_path": "/abs/path/to/data.uvh5",
  "overrides": {
    "fwhm_perturb_frac": 0.01
  },
  "slurm": {
    "cpu": {
      "time": "04:00:00",
      "nodes": 1
    }
  },
  "bayeseor": {
    "cpu_precompute_driver_hypothesis": "signal_fit",
    "fwhm_perturb_frac": 0.01
  }
}
```

#### 6.1.3 Required fields

| Field | Type | Description |
|-------|------|-------------|
| `tool` | string | Tool identifier |
| `created_utc` | string | ISO 8601 creation timestamp |
| `valska_version` | string | ValSKA version that created the manifest |
| `run_id` | string | User-provided run identifier |
| `run_dir` | string | Absolute path to run directory |
| `results_root` | string | Absolute path to results root |

#### 6.1.4 Optional fields

Tools **may** include additional fields as appropriate. Common optional fields:

| Field | Type | Description |
|-------|------|-------------|
| `template_yaml` | string | Path to template used |
| `template_name` | string | Template filename |
| `data_path` | string | Path to input data |
| `overrides` | object | User-provided configuration overrides |
| `slurm` | object | SLURM configuration by stage |

#### 6.1.5 Tool-specific section

Tools **should** include a section keyed by the tool identifier containing tool-specific configuration:

```json
{
  "bayeseor": {
    "cpu_precompute_driver_hypothesis": "signal_fit",
    "fwhm_perturb_frac": 0.01
  }
}
```

```json
{
  "pyuvsim": {
    "telescope": "HERA",
    "n_channels": 128
  }
}
```

### 6.2 jobs.json

#### 6.2.1 Purpose

Records what was actually submitted to SLURM, enabling job tracking and safe resubmission.

#### 6.2.2 Schema

```json
{
  "run_dir": "/abs/path/to/run_dir",
  "manifest": "/abs/path/to/run_dir/manifest.json",
  "sbatch": "sbatch",
  "dry_run": false,
  "submitted_utc": "2025-01-15T12:34:56Z",
  "stage": "cpu,gpu",
  "jobs": {
    "cpu": {
      "job_id": "123456",
      "script": "/abs/path/to/run_dir/submit_cpu.sh",
      "dependency": null
    }
  },
  "commands": [
    "sbatch /abs/path/to/run_dir/submit_cpu.sh"
    "<exact sbatch command executed>"
  ],

  "history": [
    // Previous submission records (on resubmit)
  ]
}
```

#### 6.2.3 Required fields

| Field | Type | Description |
|-------|------|-------------|
| `run_dir` | string | Absolute path to run directory |
| `submitted_utc` | string | ISO 8601 submission timestamp |
| `jobs` | object | Job details keyed by stage name |
| `commands` | array | Exact sbatch commands executed |

#### 6.2.4 Job record fields

Each entry in `jobs` **must** include:

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | SLURM job ID (or null if dry-run) |

Additional fields **may** be included:

| Field | Type | Description |
|-------|------|-------------|
| `script` | string | Path to submit script |
| `dependency` | string | SLURM dependency specification |

---

## 7. Configuration hierarchy

### 7.1 Overview

Configuration follows a three-tier hierarchy with increasing precedence:

```
Site defaults  →  Tool defaults  →  CLI overrides
        (lowest precedence)              (highest precedence)
```

### 7.2 runtime_paths.yaml

The primary configuration file is `config/runtime_paths.yaml`. Tools **must** support loading defaults from this file.

#### 7.2.1 Site-level configuration

Top-level keys apply to all tools unless overridden:

```yaml
# Site-wide defaults
results_root: /path/to/results

data:
  root: /path/to/datasets

slurm:
  account: project-account
  partition: default-partition
```

#### 7.2.2 Tool-level configuration

Each tool has a dedicated section:

```yaml
<tool>:
  # Tool-specific paths
  repo_path: /path/to/tool

  # Execution environment
  conda_sh: "source /path/to/conda.sh"
  conda_env: tool_env

  # Default template
  default_template: default_template.yaml

  # SLURM defaults (may override site-level)
  slurm_defaults:
    partition: gpu
    time: "24:00:00"

  # Stage-specific SLURM defaults
  slurm_defaults_cpu:
    partition: cpu
    cpus_per_task: 16

  slurm_defaults_gpu:
    partition: gpu
    gres: "gpu:1"
```

### 7.3 Resolution order

For any configuration value:

1. Check CLI argument
2. Check `runtime_paths.yaml` tool section
3. Check `runtime_paths.yaml` site section
4. Apply hardcoded default (if any)

Tools **must** document which values have hardcoded defaults.

### 7.4 SLURM configuration

SLURM directives support flexible cluster adaptation:

1. Any directive set to `null` in configuration is omitted from generated scripts
2. Tools **should** provide sensible defaults for universal directives (e.g., `time`, `mem`)
3. Cluster-specific directives (e.g., `partition` vs `constraint`) **should** be configured in `runtime_paths.yaml`, not hardcoded

---

## 8. Stages and dependencies

### 8.1 Stage definition

A **stage** is a discrete unit of work with:

- A name (e.g., `cpu_precompute`, `gpu_run`, `simulate`)
- A SLURM submit script
- Zero or more dependencies on other stages
- Resumability semantics

### 8.2 Declaring stages

Tools **must** document their stages, including:

| Property | Description |
|----------|-------------|
| Name | Stage identifier |
| Purpose | What the stage computes |
| Dependencies | Other stages that must complete first |
| Resumable | Whether the stage can resume from partial output |
| Resource profile | Typical resource requirements (CPU/GPU/memory) |

**Example (BayesEoR):**

| Stage | Purpose | Dependencies | Resumable |
|-------|---------|--------------|-----------|
| `cpu_precompute` | Compute instrument matrices | None | No |
| `signal_fit` | Bayesian inference (signal hypothesis) | `cpu_precompute` | Yes (MultiNest) |
| `no_signal` | Bayesian inference (null hypothesis) | `cpu_precompute` | Yes (MultiNest) |

**Example (pyuvsim):**

| Stage | Purpose | Dependencies | Resumable |
|-------|---------|--------------|-----------|
| `simulate` | Generate simulated visibilities | None | No |

### 8.3 Single-stage tools

Tools with only one stage **must** still follow the stage abstraction:

- Generate a submit script named `submit_<stage>.sh`
- Support `--stage <name>` in the submit CLI (even if only one option exists)
- Record stage in `jobs.json`

This ensures consistency and allows future extension.

---

## 9. Runner abstraction

### 9.1 Purpose

The runner abstraction encapsulates how an external tool is executed, supporting multiple backends without changing the overall workflow.

### 9.2 Supported runners

Tools **should** support these runner types:

#### 9.2.1 Conda runner

Executes the tool within a conda environment.

**Configuration:**
```yaml
<tool>:
  conda_sh: "source /path/to/conda.sh"
  conda_env: environment_name
```

**Script generation pattern:**
```bash
# Activate conda environment
source /path/to/conda.sh
conda activate environment_name

# Execute tool
python /path/to/tool/script.py --config config.yaml
```

#### 9.2.2 Container runner

Executes the tool within an Apptainer/Singularity container.

**Configuration:**
```yaml
<tool>:
  container_image: /path/to/image.sif
  container_bind: "/data:/data,/scratch:/scratch"
```

**Script generation pattern:**
```bash
# Execute via container
apptainer exec \
  --bind /data:/data,/scratch:/scratch \
  /path/to/image.sif \
  python /app/script.py --config config.yaml
```

### 9.3 Runner selection

Tools **may** support runner selection via:

1. Explicit CLI argument (e.g., `--runner conda`)
2. Configuration in `runtime_paths.yaml`
3. Auto-detection based on available configuration

The selected runner **must** be recorded in `manifest.json`.

---

## 10. Exit codes

### 10.1 Standard exit codes

All CLI entry points **must** use these exit codes consistently:

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments or missing required configuration |
| 3 | Missing dependencies (e.g., run directory not prepared) |
| 4 | SLURM submission failed |

### 10.2 Error reporting

On non-zero exit:

1. Print a clear error message to stderr
2. Include the specific cause if known
3. Suggest remediation if possible

**Example:**
```
ERROR: Run directory not found: /path/to/run_dir
  Hint: Run 'valska-pyuvsim-prepare' first to create the run directory.
```

---

## 11. Sweep support (optional)

### 11.1 Purpose

Sweeps orchestrate multiple runs across a parameter space. This is an **optional** capability — tools may implement it if appropriate for their use case.

### 11.2 Entry point

```
valska-<tool>-sweep
```

### 11.3 Sweep directory structure

Sweeps **should** create a container directory with:

```
<results_root>/<tool>/<taxonomy>/_sweeps/<sweep_id>/
├── sweep_manifest.json
├── <point_label_1>/
│   ├── manifest.json
│   ├── jobs.json
│   └── ...
├── <point_label_2>/
│   └── ...
└── ...
```

### 11.4 sweep_manifest.json

Records sweep-level metadata:

```json
{
  "tool": "bayeseor",
  "created_utc": "2025-01-15T12:34:56Z",
  "sweep_id": "fwhm_sweep_001",
  "sweep_dir": "/abs/path/to/results/bayeseor/_sweeps/fwhm_sweep_001",
  "parameter": "fwhm_perturb_frac",
  "values": [0.0, 0.01, 0.02],
  "points": [
    {
      "label": "fwhm_0p00",
      "value": 0.0,
      "run_dir": "/abs/path/to/results/bayeseor/fwhm_0p00",
      "manifest": "/abs/path/to/results/bayeseor/fwhm_0p00/manifest.json",
      "jobs_json": "/abs/path/to/results/bayeseor/fwhm_0p00/jobs.json"
    }
  ]
}
```

### 11.5 Sweep CLI arguments

Sweep CLIs **should** support:

| Argument | Description |
|----------|-------------|
| `--<param>-values` | Explicit list of values |
| `--<param>-values-file` | File containing values (one per line) |
| `--submit-stage` | Which stage(s) to submit after prepare |
| `--dry-run` | Preview without creating files |
| `--submit-dry-run` | Create files but don't submit jobs |

---

## 12. Module structure

### 12.1 Recommended layout

Tools **should** follow this module structure:

```
src/valska/external_tools/<tool>/
├── __init__.py          # Public API exports
├── cli_prepare.py       # Prepare CLI implementation
├── cli_submit.py        # Submit CLI implementation
├── cli_sweep.py         # Sweep CLI implementation (optional)
├── setup.py             # Prepare logic (run directory creation)
├── submit.py            # Submit logic (SLURM interaction)
├── runner.py            # Runner abstractions
├── slurm.py             # SLURM script generation
├── templates.py         # Template discovery and loading
└── templates/           # Shipped configuration templates
    ├── default.yaml
    └── ...
```

### 12.2 Public API

The module `__init__.py` **should** export:

- Prepare function(s)
- Submit function(s)
- Runner classes
- Template access utilities
- Exception classes

**Example:**
```python
from .runner import CondaRunner, ContainerRunner
from .setup import prepare_run
from .submit import submit_run, SubmissionError
from .templates import get_template_path, list_templates

__all__ = [
    "prepare_run",
    "submit_run",
    "SubmissionError",
    "get_template_path",
    "list_templates",
    "CondaRunner",
    "ContainerRunner",
]
```

---

## 13. Testing requirements

### 13.1 Required tests

Tool integrations **must** include tests for:

1. **Prepare dry-run** — Verify no files created, correct output
2. **Prepare execution** — Verify run directory structure and contents
3. **Manifest schema** — Verify required fields present and valid
4. **Submit dry-run** — Verify no jobs submitted, correct output
5. **Configuration resolution** — Verify hierarchy precedence

### 13.2 Recommended tests

Tool integrations **should** include tests for:

1. **Template rendering** — Verify templates produce valid tool configuration
2. **SLURM script validity** — Verify generated scripts are syntactically correct
3. **Resubmission** — Verify jobs.json archival and fresh submission
4. **Error handling** — Verify appropriate exit codes and messages

---

## 14. Versioning and compatibility

### 14.1 Provenance tracking

The `valska_version` field in `manifest.json` records the exact version of ValSKA that created the file. Since ValSKA uses `setuptools_scm`, this version includes the git commit hash, enabling:

1. **Exact code traceability** — Any manifest can be traced to the commit that produced it
2. **Schema archaeology** — Git history shows what fields were expected at any version
3. **Debugging** — Version differences help diagnose compatibility issues

### 14.2 Validation on read

Rather than explicit schema versioning, tools **should** validate files when reading:

1. Check for required fields; error clearly if missing
2. Ignore unknown fields (forward compatibility)
3. Include the `valska_version` in error messages to aid debugging

**Example error:**

    ERROR: Manifest missing required field 'tool'
      File: /path/to/manifest.json
      Created by: valska 0.1.1.dev40+ge43c1b807
      Hint: This manifest may predate the 'tool' field requirement.

---

### 14.3 Backwards compatibility

When evolving schemas:

1. New optional fields may be added freely
2. New required fields should include clear error messages referencing when the field became required
3. Removed or renamed fields should be handled gracefully during a transition period

---

## 15. Checklist for new tools

When implementing a new tool integration, verify:

- [ ] CLI entry points registered in `pyproject.toml`
- [ ] Naming follows `valska-<tool>-prepare`, `valska-<tool>-submit`
- [ ] Prepare creates run directory with `manifest.json` and submit scripts
- [ ] Submit reads run directory and creates `jobs.json`
- [ ] `--dry-run` supported for both prepare and submit
- [ ] Configuration loads from `runtime_paths.yaml`
- [ ] SLURM directives configurable and nullable
- [ ] Stages documented with dependencies and resumability
- [ ] Exit codes follow standard conventions
- [ ] Error messages are clear and actionable
- [ ] Tests cover prepare, submit, and configuration resolution

---

## Appendix A: Reference implementation

The BayesEoR integration (`src/valska/external_tools/bayeseor/`) serves as the reference implementation for this specification.

Key files:
- `cli_prepare.py` — Prepare CLI
- `cli_submit.py` — Submit CLI
- `setup.py` — Run directory creation and manifest writing
- `submit.py` — SLURM submission logic
- `slurm.py` — Submit script generation
- `runner.py` — Conda and container runner definitions

---

## Appendix B: Glossary

| Term | Definition |
|------|------------|
| **Artefact** | Any file generated by the prepare phase |
| **Entry point** | A CLI command registered via `pyproject.toml` |
| **Manifest** | The `manifest.json` provenance record |
| **Prepare** | Generate run artefacts without execution |
| **Provenance** | Metadata recording how a run was configured |
| **Run directory** | Self-contained directory for a single execution |
| **Runner** | Abstraction for tool execution (conda/container) |
| **Stage** | A discrete unit of work within a tool's execution |
| **Submit** | Send prepared artefacts to SLURM for execution |
| **Sweep** | Multiple runs across a parameter space |
| **Taxonomy** | Tool-specific directory hierarchy (e.g., beam/sky) |


---

## Appendix C: Reference implementation conformance

This appendix tracks the conformance status of the BayesEoR reference implementation against this specification. Items listed here are known gaps to be addressed before the specification is finalised as version 1.0.

### C.1 Conformance summary

| Requirement | Section | Status | Notes |
|-------------|---------|--------|-------|
| CLI naming convention | §2.1 | ✅ Compliant | |
| Entry point registration | §2.3 | ✅ Compliant | |
| Prepare/submit separation | §3, §4 | ✅ Compliant | |
| `--dry-run` support | §3.4, §4.3 | ✅ Compliant | |
| Run directory structure | §5 | ✅ Compliant | |
| `manifest.json` creation | §6.1 | ✅ Compliant | Resolved: 2026-01-25 |
| `jobs.json` creation | §6.2 | ✅ Compliant | |
| Configuration hierarchy | §7 | ✅ Compliant | |
| Stage abstraction | §8 | ✅ Compliant | |
| Runner abstraction | §9 | ✅ Compliant | |
| Exit codes | §10 | ✅ Compliant | Resolved: 2026-01-25 |
| SLURM dependency handling | §4.5 | ✅ Compliant | |
| Resubmission with archival | §4.6 | ✅ Compliant | |

### C.2 Outstanding items

#### C.2.1 Missing `tool` field in manifest.json

**Specification reference:** §6.1.3

**Current state:** Resolved — the `manifest.json` now includes a `tool` field identifying the generating tool.

**Resolution:** Added `tool` field to manifest generation in `src/valska/external_tools/bayeseor/setup.py` (uses canonical `TOOL_NAME`). Tests updated to assert presence (`tests/test_utils.py`); full test-suite passes.

**Priority:** Resolved.

---

#### C.2.2 Exit codes not audited

**Specification reference:** §10.1

**Current state:** Resolved — exit codes are mapped consistently across prepare, submit, and sweep CLIs.

**Resolution:** Updated error handling to use exit codes 2/3/4 per the specification, including submit-time differentiation between invalid arguments, missing dependencies, and SLURM failures.

**Priority:** Resolved.

---

#### C.2.3 `--results-root` argument not verified

**Specification reference:** §3.3

**Current state:** Resolved — `valska-bayeseor-prepare` already supports `--results-root` as a CLI argument.

**Resolution:** Verified in `src/valska/external_tools/bayeseor/cli_prepare.py` (argument defined with default resolution via runtime paths).

**Priority:** Resolved.

---

### C.3 Resolution plan

All outstanding items in Appendix C are now resolved. The specification status has been updated from "Draft" to "1.0" released.
