# Tool Implementer's Guide

**Version:** 1.1.0-draft
**Status:** Draft
**Last updated:** 2026-11-26

---

## 1. Introduction

### 1.1 Purpose

This guide provides a practical walkthrough for implementing a new external tool integration in ValSKA. It complements the [External Tool Integration Specification](external_tool_integration_spec.md) by offering step-by-step instructions, concrete examples, and implementation patterns.

### 1.2 Audience

This guide is intended for developers who:

- Are adding a new external tool to ValSKA
- Have read the External Tool Integration Specification
- Are familiar with Python packaging and CLI development
- Understand SLURM batch scheduling concepts

### 1.3 Running example

This guide uses **pyuvsim** as the running example — a visibility simulator that will be integrated as a single-stage, CPU-based tool. The patterns shown apply equally to other tools with different characteristics.

### 1.4 Prerequisites

Before starting, ensure you have:

- A working ValSKA development environment
- Access to the external tool (pyuvsim) and its documentation
- Understanding of the tool's configuration format and execution model

---

## 2. Planning your integration

### 2.1 Key questions to answer

Before writing code, answer these questions about your tool:

| Question | Example (pyuvsim) |
|----------|-------------------|
| What stages does execution involve? | Single stage: `simulate` |
| What resources does each stage require? | CPU-bound, multi-core |
| Is any stage resumable? | No |
| What configuration format does the tool use? | YAML |
| How is the tool invoked? | `python -m pyuvsim.uvsim <config>` |
| What execution environments are supported? | Conda, container |
| What input data is required? | Telescope config, sky model, observation parameters |
| What outputs are produced? | UVH5 visibility file |

### 2.2 Define your stages

Document your stages using the format from §8.2 of the specification:

**pyuvsim stages:**

| Stage | Purpose | Dependencies | Resumable | Resource profile |
|-------|---------|--------------|-----------|------------------|
| `simulate` | Generate simulated visibilities | None | No | CPU, 16–64 cores, 32GB+ memory |

For single-stage tools, this table has one row — that's fine. The stage abstraction still applies.

### 2.3 Define your taxonomy

The taxonomy determines the directory hierarchy under `<results_root>/<tool>/`. Choose a structure that:

- Groups related runs logically
- Supports your typical query patterns
- Remains stable as usage evolves

**Example taxonomies:**

| Tool | Taxonomy | Rationale |
|------|----------|-----------|
| BayesEoR | `<beam_model>/<sky_model>` | Primary analysis dimensions |
| pyuvsim | `<telescope>/<observation_id>` | Groups by instrument and observation |

Your taxonomy is encoded in how you construct the run directory path (see §4.4).

---

## 3. Module structure

### 3.1 Create the module directory

Create the tool module under `src/valska/external_tools/`:

```bash
mkdir -p src/valska/external_tools/pyuvsim/templates
touch src/valska/external_tools/pyuvsim/__init__.py
touch src/valska/external_tools/pyuvsim/cli_prepare.py
touch src/valska/external_tools/pyuvsim/cli_submit.py
touch src/valska/external_tools/pyuvsim/setup.py
touch src/valska/external_tools/pyuvsim/submit.py
touch src/valska/external_tools/pyuvsim/runner.py
touch src/valska/external_tools/pyuvsim/templates.py
```

Most new tools should reuse the shared infrastructure in:
- `valska.external_tools.common.runner`
- `valska.external_tools.common.slurm`
- `valska.external_tools.common.submit`

and therefore do not normally require a tool-specific `slurm.py`. Create a tool-specific 
`slurm.py` only if the shared Slurm rendering framework cannot support a genuinely 
tool-specific requirement.

#### 3.2 File responsibilities

| File | Responsibility |
|--------|--------|
| `__init__.py` | Public API exports |
| `cli_prepare.py` | CLI entry point for `valska-<tool>-prepare` |
| `cli_submit.py` | CLI entry point for `valska-<tool>-submit` |
| `setup.py` | Run preparation, configuration generation, command generation and manifest creation |
| `submit.py` | Tool-specific submission plan, workflow stages and submission options |
| `runner.py` | Optional tool-specific installation metadata extending the shared runner framework |
| `templates.py` | Template discovery and loading utilities |
| `templates/` | Shipped configuration templates |

The following infrastructure is shared across tools:

| Module | Responsibility |
|----------|----------|
| `common.runner` | Shared runner abstractions (`ToolInstall`, `CondaRunner`, `ContainerRunner`) |
| `common.slurm` | Shared Slurm rendering |
| `common.submit` | Shared submission orchestration, jobs.json handling and history tracking |

### 3.3 Register entry points

Add CLI entry points to `pyproject.toml`:

```toml
[project.scripts]
# ...existing entries...
valska-pyuvsim-prepare = "valska.external_tools.pyuvsim.cli_prepare:main"
valska-pyuvsim-submit = "valska.external_tools.pyuvsim.cli_submit:main"
```

After adding these, reinstall the package in development mode:

```bash
pip install -e .
```

---

## 4. Implementing the prepare phase

### 4.1 Overview

The prepare phase:

1. Parses CLI arguments
2. Loads configuration from `runtime_paths.yaml`
3. Resolves paths and merges overrides
4. Creates the run directory
5. Writes tool configuration files
6. Generates SLURM submit scripts
7. Writes `manifest.json`

### 4.2 CLI argument design

Design arguments that are:

- **Specific** — Named for what they control, not implementation details
- **Overridable** — Allow CLI to override config file defaults
- **Documentable** — Clear help text for each argument

**Example argument structure for pyuvsim:**

```python
# filepath: src/valska/external_tools/pyuvsim/cli_prepare.py

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="valska-pyuvsim-prepare",
        description="Prepare a pyuvsim simulation run directory.",
    )

    # Required identifiers
    parser.add_argument(
        "--run-id",
        required=True,
        help="Unique identifier for this run.",
    )

    # Taxonomy components
    parser.add_argument(
        "--telescope",
        required=True,
        help="Telescope name (e.g., HERA, SKA-Low).",
    )
    parser.add_argument(
        "--observation-id",
        default="default",
        help="Observation identifier for grouping runs.",
    )

    # Input specification
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to pyuvsim configuration YAML.",
    )
    parser.add_argument(
        "--telescope-config",
        type=Path,
        help="Path to telescope configuration (overrides config file).",
    )
    parser.add_argument(
        "--sky-model",
        type=Path,
        help="Path to sky model file (overrides config file).",
    )

    # Template-based configuration (alternative to --config)
    parser.add_argument(
        "--template",
        help="Use a shipped template by name (e.g., 'hera_validation').",
    )

    # Path overrides
    parser.add_argument(
        "--results-root",
        type=Path,
        help="Override results root directory.",
    )

    # SLURM overrides
    parser.add_argument(
        "--partition",
        help="SLURM partition override.",
    )
    parser.add_argument(
        "--time",
        help="SLURM time limit override.",
    )
    parser.add_argument(
        "--cpus-per-task",
        type=int,
        help="SLURM CPUs per task override.",
    )
    parser.add_argument(
        "--mem",
        help="SLURM memory override.",
    )

    # Execution control
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without creating files.",
    )

    return parser
```

### 4.3 Loading configuration

Load and merge configuration following the hierarchy:

```python
# filepath: src/valska/external_tools/pyuvsim/cli_prepare.py

from pathlib import Path
from typing import Any
import yaml

def load_runtime_config() -> dict[str, Any]:
    """Load runtime_paths.yaml configuration."""
    config_path = Path(__file__).parents[4] / "config" / "runtime_paths.yaml"
    if not config_path.exists():
        return {}
    with config_path.open() as f:
        return yaml.safe_load(f) or {}


def get_tool_config(runtime: dict[str, Any]) -> dict[str, Any]:
    """Extract pyuvsim-specific configuration."""
    return runtime.get("pyuvsim", {})


def resolve_results_root(
    cli_override: Path | None,
    runtime: dict[str, Any],
) -> Path:
    """Resolve results root with precedence: CLI > config > error."""
    if cli_override is not None:
        return cli_override

    root = runtime.get("results_root")
    if root is not None:
        return Path(root)

    raise ValueError(
        "No results_root configured. "
        "Set in runtime_paths.yaml or pass --results-root."
    )
```

### 4.4 Building the run directory path

Construct the run directory following your taxonomy:

```python
# filepath: src/valska/external_tools/pyuvsim/setup.py

from pathlib import Path

def build_run_dir(
    results_root: Path,
    telescope: str,
    observation_id: str,
    run_id: str,
    unique: bool = False,
) -> Path:
    """
    Construct the run directory path.

    Structure: <results_root>/pyuvsim/<telescope>/<observation_id>/<run_id>/
    """
    run_dir = results_root / "pyuvsim" / telescope / observation_id / run_id

    if unique:
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = run_dir / timestamp

    return run_dir
```

### 4.5 Writing the manifest

Create `manifest.json` with all required fields:

```python
# filepath: src/valska/external_tools/pyuvsim/setup.py

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from valska import __version__

def write_manifest(
    run_dir: Path,
    *,
    run_id: str,
    results_root: Path,
    telescope: str,
    observation_id: str,
    config_path: Path,
    template_name: str | None,
    slurm_config: dict[str, Any],
    tool_config: dict[str, Any],
) -> Path:
    """Write manifest.json to run directory."""

    manifest = {
        # Required fields (per spec §6.1.3)
        "tool": "pyuvsim",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "valska_version": __version__,
        "run_id": run_id,
        "run_dir": str(run_dir.resolve()),
        "results_root": str(results_root.resolve()),

        # Taxonomy
        "telescope": telescope,
        "observation_id": observation_id,

        # Configuration sources
        "config_yaml": str(config_path.resolve()),
        "template_name": template_name,

        # SLURM configuration by stage
        "slurm": {
            "simulate": slurm_config,
        },

        # Tool-specific section
        "pyuvsim": tool_config,
    }

    manifest_path = run_dir / "manifest.json"
    with manifest_path.open("w") as f:
        json.dump(manifest, f, indent=2)

    return manifest_path
```

### 4.6 Generating SLURM submit scripts

#### 4.6 Generating SLURM submit scripts

Most tools should use the shared Slurm renderer provided by:

```python
valska.external_tools.common.slurm
```

The shared renderer handles:

- SBATCH directive generation.
- Conda activation.
- Array jobs.
- Diagnostics logging.
- Timing files.
- Command execution wrappers.

Rather than generating Slurm scripts directly, tool integrations should focus on generating the commands that need to be executed.

For example:

```python
commands = prepare_mytool_commands(...)
```

The shared renderer then embeds these commands within a standardised Slurm script.

Tools should only implement their own Slurm renderer if they require behaviour that cannot reasonably be represented using the shared framework.

As a rule:

- Tools generate commands.
- The shared framework generates Slurm scripts.


### 4.7 Runner definitions

#### 4.7 Runner definitions

Most tools should reuse the shared runner abstractions provided by:

```python
from valska.external_tools.common.runner import (
    ToolInstall,
    CondaRunner,
    ContainerRunner,
)
```

`CondaRunner` and `ContainerRunner` provide common execution environments that can be shared across multiple tools.

Tool-specific runner modules should normally only define installation metadata.

For example:

```python
from dataclasses import dataclass
from pathlib import Path

from valska.external_tools.common.runner import ToolInstall


@dataclass(frozen=True)
class MyToolInstall(ToolInstall):
    run_script: Path
```

This pattern is used by BayesEoR, which extends `ToolInstall` while reusing the shared runner implementations unchanged.

Avoid creating tool-specific copies of `CondaRunner` or `ContainerRunner` unless genuinely new execution behaviour is required.

### 4.8 Main prepare function

Bring it all together:

```python
# filepath: src/valska/external_tools/pyuvsim/setup.py

from pathlib import Path
from typing import Any
import shutil

from .runner import CondaRunner, ContainerRunner
from .slurm import render_submit_script

def prepare_pyuvsim_run(
    *,
    run_id: str,
    results_root: Path,
    telescope: str,
    observation_id: str,
    config_path: Path,
    runner: CondaRunner | ContainerRunner,
    slurm_config: dict[str, Any],
    template_name: str | None = None,
    tool_config: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Prepare a pyuvsim run directory.

    Returns a dict with:
        - run_dir: Path to created run directory
        - manifest: Path to manifest.json
        - submit_script: Path to submit script
    """

    # Build run directory path
    run_dir = build_run_dir(
        results_root=results_root,
        telescope=telescope,
        observation_id=observation_id,
        run_id=run_id,
    )

    if dry_run:
        return {
            "run_dir": run_dir,
            "dry_run": True,
            "would_create": [
                run_dir / "manifest.json",
                run_dir / "config.yaml",
                run_dir / "submit_simulate.sh",
            ],
        }

    # Create run directory
    run_dir.mkdir(parents=True, exist_ok=True)

    # Copy configuration to run directory
    run_config = run_dir / "config.yaml"
    shutil.copy(config_path, run_config)

    # Generate submit script
    submit_script_content = render_submit_script(
        runner=runner,
        config_yaml=run_config,
        run_dir=run_dir,
        slurm=slurm_config,
    )
    submit_script = run_dir / "submit_simulate.sh"
    submit_script.write_text(submit_script_content)
    submit_script.chmod(0o755)

    # Write manifest
    manifest_path = write_manifest(
        run_dir=run_dir,
        run_id=run_id,
        results_root=results_root,
        telescope=telescope,
        observation_id=observation_id,
        config_path=config_path,
        template_name=template_name,
        slurm_config=slurm_config,
        tool_config=tool_config or {},
    )

    return {
        "run_dir": run_dir,
        "manifest": manifest_path,
        "submit_script": submit_script,
        "config": run_config,
    }
```

### 4.9 CLI main function

Wire up the CLI:

```python
# filepath: src/valska/external_tools/pyuvsim/cli_prepare.py

#!/usr/bin/env python3
"""CLI entry point for valska-pyuvsim-prepare."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .runner import CondaRunner, ContainerRunner
from .setup import prepare_pyuvsim_run


def build_parser() -> argparse.ArgumentParser:
    # ... (as shown in §4.2)
    pass


def load_runtime_config() -> dict[str, Any]:
    # ... (as shown in §4.3)
    pass


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        # Load configuration
        runtime = load_runtime_config()
        tool_config = runtime.get("pyuvsim", {})

        # Resolve paths
        results_root = resolve_results_root(args.results_root, runtime)

        # Build runner
        runner = CondaRunner(
            conda_sh=tool_config.get("conda_sh", "source ~/conda.sh"),
            conda_env=tool_config.get("conda_env", "pyuvsim"),
        )

        # Build SLURM config with overrides
        slurm_config = build_slurm_config(tool_config, args)

        # Resolve config path
        if args.template:
            config_path = get_template_path(args.template)
        elif args.config:
            config_path = args.config
        else:
            print("ERROR: Must specify --config or --template", file=sys.stderr)
            return 2

        # Prepare the run
        result = prepare_pyuvsim_run(
            run_id=args.run_id,
            results_root=results_root,
            telescope=args.telescope,
            observation_id=args.observation_id,
            config_path=config_path,
            runner=runner,
            slurm_config=slurm_config,
            template_name=args.template,
            dry_run=args.dry_run,
        )

        # Output
        if args.dry_run:
            print("[DRY RUN] Would create:")
            for path in result["would_create"]:
                print(f"  {path}")
            print(f"\nRun directory: {result['run_dir']}")
        else:
            print(f"Run directory: {result['run_dir']}")
            print(f"Manifest: {result['manifest']}")
            print(f"Submit script: {result['submit_script']}")
            print()
            print("Next steps:")
            print(f"  valska-pyuvsim-submit {result['run_dir']}")

        return 0

    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

---

## 5. Implementing the submit phase

### 5. Implementing the submit phase

#### 5.1 Overview

The submit phase:

- Validates that the run directory exists and has been prepared.
- Loads and validates `manifest.json`.
- Resolves workflow stages.
- Submits jobs through Slurm.
- Records submission metadata in `jobs.json`.
- Tracks submission history.

Most of this functionality is now provided by the shared submission framework in:

```python
valska.external_tools.common.submit
```

Tool integrations are responsible for defining stages, dependencies, installation-specific behaviour, and tool-specific submission options.

---

#### 5.2 RunOptions

Tools should define a `RunOptions` subclass whenever additional submission options are required.

Example:

```python
from dataclasses import dataclass

from valska.external_tools.common.submit import RunOptions


@dataclass
class MyToolRunOptions(RunOptions):
    my_option: str = "default"
```

The shared framework already provides common submission options:

```python
sbatch_exe
dry_run
force
depend_afterok
record
```

Tool-specific options should be limited to behaviour unique to the tool.

---

#### 5.3 Defining stages

Workflows are represented as collections of stages.

A stage corresponds to an independently submittable workflow component such as:

```text
simulate
beamcheck
cpu_precompute
signal_fit
```

Stages are defined using:

```python
from valska.external_tools.common.submit import Stage


SIMULATE = Stage(
    name="simulate",
    method=submit_simulate,
)
```

Each stage method performs tool-specific submission logic and updates the submission record.

Example:

```python
def submit_simulate(plan, result):
    ...
    return result
```

Stage methods should:

- Submit jobs.
- Update job records.
- Record commands.
- Return the updated result structure.

The shared framework handles jobs.json persistence, history recording, and common metadata automatically.

---

#### 5.4 Creating a SubmitPlan

Each tool defines a `SubmitPlan` subclass.

The `SubmitPlan` is responsible for:

- Loading manifest information.
- Resolving artefact locations.
- Validating existing submissions.
- Defining available workflow stages.
- Providing stage-specific context.

Typical structure:

```python
class MyToolSubmitPlan(
    SubmitPlan[MyToolRunOptions]
):
    ...
```

Tool-specific plans should focus on workflow semantics rather than generic submission orchestration.

---

#### 5.5 Stage resolution

The `SubmitPlan` determines which stages execute for a given stage selection.

Example:

```python
{
    "simulate": [SIMULATE],
    "all": [SIMULATE, BEAMCHECK],
}
```

This allows individual stage submission while preserving explicit workflow ordering.

Stage resolution should be deterministic and testable.

---

#### 5.6 Using the shared submission framework

Submission is normally performed using:

```python
submit_tool_run(...)
```

The framework automatically handles:

- Manifest loading.
- Stage execution.
- jobs.json generation.
- Submission history.
- Dry-run support.
- Duplicate submission protection.
- Force resubmission.
- Dependency handling.

Tool implementations should focus on workflow behaviour rather than submission plumbing.

---

#### 5.7 Submit CLI

The submit CLI remains responsible for:

- Parsing user arguments.
- Constructing `RunOptions`.
- Selecting stages.
- Invoking the tool submission plan.

Typical flow:

```python
options = MyToolRunOptions(
    sbatch_exe=args.sbatch,
    dry_run=args.dry_run,
)

submit_tool_run(
    run_dir=args.run_dir,
    stage_id=args.stage,
    submit_plan=MyToolSubmitPlan,
    options=options,
)
```

The CLI should not directly implement:

- Submission orchestration.
- jobs.json handling.
- History tracking.
- Stage execution logic.

These responsibilities belong in the shared submission framework.


---

## 6. Configuration in runtime_paths.yaml

### 6.1 Tool section structure

Add a section for your tool in `config/runtime_paths.yaml`:

```yaml
# filepath: config/runtime_paths.yaml

# ... existing content ...

pyuvsim:
  # Conda settings
  conda_sh: "source /home/user/miniforge3/etc/profile.d/conda.sh"
  conda_env: pyuvsim

  # Container settings (alternative to conda)
  # container_image: /path/to/pyuvsim.sif
  # container_bind: "/data:/data,/scratch:/scratch"

  # Default template
  default_template: hera_validation.yaml

  # SLURM defaults for simulate stage
  slurm_defaults:
    partition: cpu
    time: "04:00:00"
    mem: "32G"
    cpus_per_task: 16
    nodes: 1
    ntasks: 1
```

### 6.2 Documenting hardcoded defaults

In your module, document which values have hardcoded defaults:

```python
# filepath: src/valska/external_tools/pyuvsim/cli_prepare.py

def build_slurm_config(
    tool_config: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """
    Build SLURM configuration with defaults and overrides.

    Hardcoded defaults (overridden by runtime_paths.yaml, then CLI):
        - time: "04:00:00"
        - mem: "16G"
        - cpus_per_task: 8
        - nodes: 1
        - ntasks: 1
        - job_name_prefix: "pyuvsim"
    """
    # Start with hardcoded defaults
    config = {
        "time": "04:00:00",
        "mem": "16G",
        "cpus_per_task": 8,
        "nodes": 1,
        "ntasks": 1,
        "job_name_prefix": "pyuvsim",
    }

    # Merge tool defaults from runtime_paths.yaml
    slurm_defaults = tool_config.get("slurm_defaults", {})
    config.update(slurm_defaults)

    # Apply CLI overrides
    if args.partition:
        config["partition"] = args.partition
    if args.time:
        config["time"] = args.time
    if args.cpus_per_task:
        config["cpus_per_task"] = args.cpus_per_task
    if args.mem:
        config["mem"] = args.mem

    return config
```

---

## 7. Templates

### 7.1 Creating templates

Place configuration templates in the `templates/` subdirectory:

```yaml
# filepath: src/valska/external_tools/pyuvsim/templates/hera_validation.yaml

# HERA validation simulation template
# Values marked __SET_BY_VALSKA__ are replaced at prepare time

# Telescope configuration
telescope:
  name: HERA
  config_path: "__SET_BY_VALSKA__"

# Observation parameters
observation:
  start_time: 2458115.5
  duration_hours: 4.0
  integration_time: 10.0

# Frequency settings
frequency:
  start_mhz: 150.0
  end_mhz: 160.0
  n_channels: 128

# Sky model
sky_model:
  path: "__SET_BY_VALSKA__"
  type: "gleam"

# Output
output:
  path: "__SET_BY_VALSKA__"
  format: "uvh5"
```

### 7.2 Template utilities

```python
# filepath: src/valska/external_tools/pyuvsim/templates.py

from pathlib import Path


def _templates_dir() -> Path:
    """Return the templates directory path."""
    return Path(__file__).parent / "templates"


def list_templates() -> list[str]:
    """List available template names."""
    templates_dir = _templates_dir()
    if not templates_dir.exists():
        return []
    return sorted(p.name for p in templates_dir.glob("*.yaml"))


def get_template_path(name: str) -> Path:
    """
    Get the full path to a template by name.

    Parameters
    ----------
    name
        Template name (with or without .yaml extension).

    Returns
    -------
    Path to the template file.

    Raises
    ------
    FileNotFoundError
        If template does not exist.
    """
    if not name.endswith(".yaml"):
        name = f"{name}.yaml"

    path = _templates_dir() / name

    if not path.exists():
        available = list_templates()
        raise FileNotFoundError(
            f"Template not found: {name}\n"
            f"Available templates: {', '.join(available) or '(none)'}"
        )

    return path
```

---

## 8. Public API

### 8.1 Module exports

```python
# filepath: src/valska/external_tools/pyuvsim/__init__.py

"""
pyuvsim integration for ValSKA.

Primary entry points:
- prepare_pyuvsim_run: Prepare a simulation run directory.
- submit_pyuvsim_run: Submit a prepared run to SLURM.
- get_template_path: Access shipped simulation templates.
"""

from .runner import CondaRunner, ContainerRunner
from .setup import prepare_pyuvsim_run
from .submit import SubmissionError, submit_pyuvsim_run
from .templates import get_template_path, list_templates

__all__ = [
    "prepare_pyuvsim_run",
    "submit_pyuvsim_run",
    "SubmissionError",
    "get_template_path",
    "list_templates",
    "CondaRunner",
    "ContainerRunner",
]
```

---

## 9. Testing

### 9.1 Required tests

#### 9.1 Required tests

Create tests in:

```text
tests/external_tools/<tool>/
```

Tool-specific tests should focus on behaviour that is unique to the tool.

### setup.py

- Configuration generation.
- Manifest generation.
- Artefact registration.
- Command generation.
- Run-directory creation.

### submit.py

- Stage definitions.
- Stage ordering.
- Dependency handling.
- Manifest interpretation.
- Tool-specific options.
- Tool-specific submission behaviour.

### CLI

- Argument parsing.
- Configuration resolution.
- Error handling.
- Exit codes.

Behaviour provided by shared infrastructure should normally be tested in the common test suites rather than duplicated across every tool.

Examples include:

- jobs.json persistence.
- Submission history.
- Duplicate-submission prevention.
- Dry-run handling.
- Common Slurm rendering.
- Common runner behaviour.




---

## 10. Checklist

Before considering your integration complete, verify:

### 10.1 Structure
- [ ] Module created under `src/valska/external_tools/<tool>/`
- [ ] Entry points registered in `pyproject.toml`
- [ ] `__init__.py` exports public API

### 10.2 Prepare phase
- [ ] CLI parses required and optional arguments
- [ ] `--dry-run` previews without creating files
- [ ] `--results-root` overrides configured default
- [ ] Run directory created with correct structure
- [ ] `manifest.json` includes all required fields
- [ ] SLURM submit script generated for each stage
- [ ] Exit codes follow specification (0, 1, 2)

### 10.3 Submit phase
- [ ] CLI accepts run directory as primary argument
- [ ] Validates run directory exists and is prepared
- [ ] `--dry-run` previews without submitting
- [ ] `--stage` selects specific stages
- [ ] `--resubmit` archives existing jobs.json
- [ ] `jobs.json` written with all required fields
- [ ] Exit codes follow specification (0, 1, 3, 4)

### 10.4 Configuration
- [ ] Tool section documented in `runtime_paths.yaml`
- [ ] Hardcoded defaults documented in code
- [ ] Configuration hierarchy respected (CLI > config > defaults)
- [ ] SLURM directives nullable (None omits directive)

### 10.5 Testing
- [ ] Prepare dry-run test
- [ ] Prepare execution test
- [ ] Manifest schema test
- [ ] Submit dry-run test
- [ ] Configuration resolution tests

---

## Appendix A: Common patterns

### A.1 Path resolution helper

```python
def resolve_path(
    cli_value: Path | None,
    config_value: str | None,
    default: Path | None = None,
    name: str = "path",
) -> Path:
    """Resolve a path with precedence: CLI > config > default."""
    if cli_value is not None:
        return cli_value
    if config_value is not None:
        return Path(config_value)
    if default is not None:
        return default
    raise ValueError(f"No {name} configured.")
```

### A.2 UTC timestamp helper

```python
from datetime import datetime, timezone

def utc_now_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()

def utc_now_compact() -> str:
    """Return current UTC time in compact format (for filenames)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
```

### A.3 Safe JSON writing

```python
import json
from pathlib import Path

def write_json_atomic(path: Path, data: dict) -> None:
    """Write JSON atomically to avoid partial writes."""
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w") as f:
        json.dump(data, f, indent=2)
    tmp_path.rename(path)
```

---

## Appendix B: Troubleshooting

### B.1 Entry points not found after installation

**Symptom:** `valska-pyuvsim-prepare: command not found`

**Solution:**
```bash
pip install -e .
hash -r  # Clear shell command cache
```

### B.2 Import errors

**Symptom:** `ModuleNotFoundError: No module named 'valska.external_tools.pyuvsim'`

**Check:**
1. `__init__.py` exists in the module directory
2. Package reinstalled after adding module

### B.3 Manifest missing required fields

**Symptom:** Tests fail on manifest validation

**Check:** Ensure `tool` field is included:

```python
manifest = {
    "tool": "pyuvsim",
    # ...
}
```