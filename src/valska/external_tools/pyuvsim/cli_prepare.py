#!/usr/bin/env python3
"""
Prepare a pyuvsim validation run "kit" under the ValSKA results directory.

This module is the importable CLI entrypoint used by the console script::

  valska-pyuvsim-prepare

What this does
--------------
This generates reproducible run artefacts for a pyuvsim simulation, without
actually running pyuvsim itself.

Specifically, it:

- resolves runtime paths (results_root, optional beamdata expansion, default template)
- instantiates the pyuvsim runner (currently conda)
- prepares a run directory containing:
  - a simulation config YAML / obsparam YAML
  - a submit script for the simulation stage
  - a manifest.json recording provenance & resolved paths

Design principles
-----------------
- setup.prepare_pyuvsim_run() is the single source of truth for canonical
  run_dir construction.

Variant concept
---------------
We include a <variant> directory level to separate template-level differences
that should never collide. By default it is derived from the template filename
stem by removing the first occurrence of "_template".

Beam/sky taxonomy
-----------------
The results tree is organised by (beam_model, sky_model), replacing the earlier
overloaded "scenario" label.

Canonical non-sweep run directory::

  <results_root>/pyuvsim/<beam_model>/<sky_model>/<variant>/<run_label>/<run_id>[/<UTCSTAMP>]

Backwards compatibility
-----------------------
- --scenario is deprecated. If used, it must be unambiguous:
  - --scenario <beam>/<sky>
  - --scenario <beam>__<sky>
- Any other form is rejected to prevent silent misrouting.

Beamdata path resolution
------------------------
If you pass --beamdata as a relative path, it is resolved using
runtime_paths.yaml:data.root if set.

Example runtime_paths.yaml::

  results_root: /share/nas-0-3/psims/validation_results/UKSRC
  data:
    root: /path/to/datasets

Then ValSKA will resolve::

  --beamdata foo/bar  ->  /path/to/datasets/foo/bar

Absolute paths are used as-is. The resolved absolute path is recorded in the
manifest.

Future container support
------------------------
Today this assumes a conda-based runner. In the future we may support
Apptainer/Singularity containers by swapping the "runner" configuration; the
produced run directory, config YAML, and scripts are designed to remain stable.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

from valska.cli_format import (
    CliColors,
    add_color_argument,
    resolve_color_mode,
)
from valska.external_tools.pyuvsim import (
    CondaRunner,
    ContainerRunner,
    compute_run_dir,
    get_template_path,
    list_templates,
    prepare_pyuvsim_run,
    pyuvsimInstall,
)
from valska.utils import get_default_path_manager, resolve_data_path


class BeamCheckArgs(TypedDict, total=False):
    make_beam_check: bool
    hours_each_side: float | None
    step_seconds: float | None
    beamcheck_runner: CondaRunner | ContainerRunner


def _utc_stamp() -> str:
    """Return a UTC timestamp suitable for directory naming."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _format_run_label_from_fwhm_frac(frac: float) -> str:
    """Format a run label from a fractional FWHM perturbation."""
    s = f"{frac:+.1e}"
    if s.startswith("+"):
        s = s[1:]
    return f"fwhm_{s}"


def _derive_variant_from_template_path(template_yaml: Path) -> str:
    """
    Derive a stable variant key from a template filename.

    Rules:
      - take filename stem
      - remove first occurrence of "_template" if present
    """
    stem = template_yaml.stem
    stem = stem.replace("_template", "", 1)
    return stem.strip("_") or template_yaml.stem


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for valska-pyuvsim-prepare."""
    parser = argparse.ArgumentParser(
        prog="valska-pyuvsim-prepare",
        description=(
            "Prepare a pyuvsim validation run directory.\n\n"
            "Canonical layout:\n"
            "  <results_root>/pyuvsim/<beam_model>/<sky_model>/<variant>/<run_label>/<run_id>/\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "--valska-root",
        type=Path,
        default=None,
        help=(
            "Root path of the ValSKA repository. If provided, pyuvsim template "
            "paths under config/pyuvsim will be rewritten to absolute paths rooted here."
        ),
    )
    # Required science axes
    parser.add_argument(
        "--beam",
        type=str,
        default=None,
        help="Beam / instrument model label (e.g. achromatic_Gaussian).",
    )
    parser.add_argument(
        "--sky",
        type=str,
        default=None,
        help="Sky model label (e.g. GLEAM, GSM, GLEAM_plus_GSM).",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help=(
            "DEPRECATED. Use --beam and --sky.\n"
            "If used, must be '<beam>/<sky>' or '<beam>__<sky>' "
            "(e.g. 'achromatic_Gaussian/GLEAM')."
        ),
    )

    parser.add_argument(
        "--beamdata",
        type=Path,
        required=False,
        default=None,
        help=(
            "Optional path to beam-related input data (e.g. CST / FEKO products). "
            "Relative paths may be resolved via runtime_paths.yaml:data.root."
        ),
    )

    parser.add_argument(
        "--run-id",
        type=str,
        required=True,
        help="Identifier for the run (e.g. r001).",
    )

    parser.add_argument(
        "--results-root",
        type=Path,
        default=None,
        help="Results root. If omitted, resolves via config/runtime_paths.yaml then env/defaults.",
    )

    parser.add_argument(
        "--unique",
        action="store_true",
        help=(
            "Append a UTC timestamp beneath run_id to ensure uniqueness.\n"
            "If omitted, may still be enabled via runtime_paths.yaml "
            "(pyuvsim.unique_by_default)."
        ),
    )

    parser.add_argument(
        "--fwhm-perturb-frac",
        type=float,
        default=None,
        help=(
            "Apply a multiplicative perturbation to fwhm_deg at prepare time, specified as a fraction.\n"
            "Example: --fwhm-perturb-frac=-1e-3 means -0.1%% (multiply by 0.999).\n"
            "Example: --fwhm-perturb-frac=1e-1 means +10%% (multiply by 1.1).\n"
            "Note: if the value is negative, use either '--fwhm-perturb-frac=-1e-3' "
            "or place '--' before the value to prevent argparse confusion."
        ),
    )

    parser.add_argument(
        "--template",
        type=str,
        default=None,
        help=(
            "Template name shipped with ValSKA OR a filesystem path to a template YAML.\n"
            "If omitted, uses pyuvsim.default_template from config/runtime_paths.yaml, "
            "otherwise defaults to default_template.yaml.\n"
            "To list shipped templates, use --list-templates."
        ),
    )
    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List shipped pyuvsim templates and exit.",
    )

    parser.add_argument(
        "--variant",
        type=str,
        default=None,
        help=(
            "Template variant key used as a directory level to avoid collisions.\n"
            "If omitted, derived from the selected template filename stem by removing "
            "the first occurrence of '_template'."
        ),
    )

    parser.add_argument(
        "--run-label",
        type=str,
        default=None,
        help=(
            "Optional run label directory component. If not provided and "
            "--fwhm-perturb-frac is set, a label is automatically generated "
            "(e.g. fwhm_1.0e-02). Otherwise defaults to 'default'."
        ),
    )

    parser.add_argument(
        "--pyuvsim-repo",
        type=Path,
        default=None,
        help="Path to local clone of pyuvsim (used for provenance and optional helper discovery).",
    )

    parser.add_argument(
        "--conda-sh",
        type=str,
        default=None,
        help="Command to source conda.sh in batch jobs (e.g. 'source /path/to/conda.sh').",
    )
    parser.add_argument(
        "--conda-env",
        type=str,
        default=None,
        help="Conda env name containing pyuvsim.",
    )

    parser.add_argument(
        "--no-conda-activate",
        action="store_true",
        help="Do not emit conda activation lines in the generated SLURM script.",
    )

    parser.add_argument(
        "--override",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override a top-level YAML key in the template (repeatable).",
    )

    # CPU / SLURM options only (pyuvsim has no GPU stage here)
    parser.add_argument(
        "--cpu-partition",
        type=str,
        default=None,
        help="SLURM partition override for simulation stage.",
    )
    parser.add_argument(
        "--cpu-constraint",
        type=str,
        default=None,
        help="SLURM constraint override for simulation stage.",
    )
    parser.add_argument(
        "--cpu-time",
        type=str,
        default=None,
        help="SLURM time override for simulation stage.",
    )
    parser.add_argument(
        "--cpu-mem",
        type=str,
        default=None,
        help="SLURM mem override for simulation stage.",
    )
    parser.add_argument(
        "--cpu-cpus-per-task",
        type=int,
        default=None,
        help="SLURM cpus-per-task for simulation stage.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved paths and intended run directory, but do not write files.",
    )

    parser.add_argument(
        "--no-beamcheck",
        dest="disable_beam_check",
        action="store_true",
        default=False,
        help="Disable the beam check simulation (enabled by default).",
    )

    parser.add_argument(
        "--beamcheck-hours",
        dest="check_hours",
        type=float,
        help=(
            "Duration in hours either side of transit for beam check simulation."
        ),
    )

    parser.add_argument(
        "--beamcheck-step-seconds",
        dest="step_seconds",
        type=float,
        help=("Time step in seconds for beam check simulation."),
    )
    add_color_argument(parser)

    return parser


def _get_nested(d: dict[str, Any], *keys: str) -> Any:
    """Safely access nested dict keys; returns None if any level is missing."""
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _parse_overrides(kvs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for kv in kvs:
        if "=" not in kv:
            raise ValueError(
                f"ERROR: Invalid --override '{kv}'. Expected KEY=VALUE."
            )
        k, v = kv.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            raise ValueError(f"ERROR: Invalid --override '{kv}'. Empty KEY.")
        out[k] = v
    return out


def _slurm_defaults(runtime: dict[str, Any]) -> dict[str, Any]:
    """
    Extract SLURM defaults from runtime_paths.yaml for pyuvsim.

    Passes through ALL keys from the config to support any SBATCH directive.
    """
    cfg = _get_nested(runtime, "pyuvsim", "slurm_defaults_cpu")
    if not isinstance(cfg, dict):
        cfg = _get_nested(runtime, "pyuvsim", "slurm_defaults")
    cfg = cfg if isinstance(cfg, dict) else {}

    defaults = {
        "time": "12:00:00",
        "mem": "8G",
        "cpus_per_task": 4,
        "nodes": 1,
        "ntasks": 1,
        "ntasks_per_node": 1,
        "job_name_prefix": "pyuvsim",
        "mpi": "pmi2",
    }

    return {**defaults, **cfg}


def _parse_beam_sky(
    *, beam: str | None, sky: str | None, scenario: str | None
) -> tuple[str, str, str]:
    """
    Preferred: --beam and --sky.

    Deprecated: --scenario in the form '<beam>/<sky>' or '<beam>__<sky>'.

    Returns (beam_model, sky_model, source_tag).
    """
    if beam and sky:
        b = beam.strip()
        k = sky.strip()
        if not b or not k:
            raise ValueError(
                "ERROR: --beam and --sky must be non-empty strings."
            )
        return b, k, "CLI(--beam/--sky)"

    if scenario:
        s = scenario.strip()
        if "/" in s:
            b, k = s.split("/", 1)
            b, k = b.strip(), k.strip()
            if b and k:
                return b, k, "DEPRECATED(--scenario)"
        if "__" in s:
            b, k = s.split("__", 1)
            b, k = b.strip(), k.strip()
            if b and k:
                return b, k, "DEPRECATED(--scenario)"
        raise ValueError(
            "ERROR: --scenario is deprecated and must be of the form '<beam>/<sky>' "
            "or '<beam>__<sky>' (e.g. 'achromatic_Gaussian/GLEAM'). "
            "Please use --beam and --sky."
        )

    raise ValueError("ERROR: You must provide --beam and --sky (recommended).")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for valska-pyuvsim-prepare."""
    parser = build_parser()
    args = parser.parse_args(argv)
    colors = CliColors(resolve_color_mode(args.color))

    if args.list_templates:
        for name in list_templates():
            print(name)
        return 0

    try:
        beam_model, sky_model, beam_sky_src = _parse_beam_sky(
            beam=args.beam, sky=args.sky, scenario=args.scenario
        )
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    pm = get_default_path_manager()
    runtime = pm.runtime_paths

    valska_root = None
    valska_root_src = None

    if args.valska_root is not None:
        valska_root = Path(args.valska_root).expanduser().resolve()
        valska_root_src = "CLI"
    else:
        cfg_root = _get_nested(runtime, "pyuvsim", "valska_root")
        if cfg_root:
            valska_root = Path(str(cfg_root)).expanduser().resolve()
            valska_root_src = "runtime_paths.yaml"

    # results_root
    if args.results_root is not None:
        results_root = Path(args.results_root).expanduser()
        results_root_src = "CLI"
    else:
        results_root = Path(pm.results_root).expanduser()
        results_root_src = (
            "runtime_paths.yaml"
            if "results_root" in runtime
            else "env/default"
        )

    # unique default via runtime_paths.yaml
    unique = bool(args.unique)
    if not args.unique:
        cfg_unique = _get_nested(runtime, "pyuvsim", "unique_by_default")
        if isinstance(cfg_unique, bool):
            unique = cfg_unique

    # beamdata resolution (optional)
    beamdata_path: Path | None = None
    beamdata_src: str | None = None
    if args.beamdata is not None:
        try:
            beamdata_path = resolve_data_path(args.beamdata, runtime)
            beamdata_src = "runtime_paths.yaml:data.root"
        except Exception:
            beamdata_path = Path(args.beamdata).expanduser()
            beamdata_src = "CLI"

    # run_label
    if args.run_label is not None and str(args.run_label).strip():
        run_label = str(args.run_label).strip()
        run_label_src = "CLI(--run-label)"
    else:
        if args.fwhm_perturb_frac is not None:
            run_label = _format_run_label_from_fwhm_frac(
                float(args.fwhm_perturb_frac)
            )
            run_label_src = "auto(--fwhm-perturb-frac)"
        else:
            run_label = "default"
            run_label_src = "default"

    # pyuvsim repo path
    repo_path = args.pyuvsim_repo
    repo_src = "CLI"
    if repo_path is None:
        cfg_repo = _get_nested(runtime, "pyuvsim", "repo_path")
        if cfg_repo:
            repo_path = Path(str(cfg_repo)).expanduser()
            repo_src = "runtime_paths.yaml"

    if repo_path is None:
        print(
            "ERROR: pyuvsim repo path not provided. Pass --pyuvsim-repo or set "
            "pyuvsim.repo_path in config/runtime_paths.yaml.",
            flush=True,
        )
        return 2

    # conda settings
    conda_sh = args.conda_sh
    conda_env = args.conda_env
    conda_src = "CLI"
    if conda_sh is None:
        cfg = _get_nested(runtime, "pyuvsim", "conda_sh")
        if cfg:
            conda_sh = str(cfg)
            conda_src = "runtime_paths.yaml"
    if conda_env is None:
        cfg = _get_nested(runtime, "pyuvsim", "conda_env")
        if cfg:
            conda_env = str(cfg)
            conda_src = "runtime_paths.yaml"

    if args.no_conda_activate:
        conda_sh = None
        conda_env = None
        conda_src = "disabled(--no-conda-activate)"
    else:
        if conda_sh is None or conda_env is None:
            print(
                "ERROR: conda settings not fully specified. Provide --conda-sh and "
                "--conda-env or set pyuvsim.conda_sh and pyuvsim.conda_env in "
                "config/runtime_paths.yaml, or pass --no-conda-activate.",
                flush=True,
            )
            return 2

    # Template
    template_arg = args.template
    template_src = "CLI"
    if template_arg is None:
        cfg_t = _get_nested(runtime, "pyuvsim", "default_template")
        if cfg_t:
            template_arg = str(cfg_t)
            template_src = "runtime_paths.yaml"
        else:
            template_arg = "default_template.yaml"
            template_src = "default"

    template_path = Path(str(template_arg)).expanduser()

    if template_path.exists():
        template_yaml = template_path

    elif valska_root is not None:
        candidate = (valska_root / template_path).resolve()

        if candidate.exists():
            template_yaml = candidate
        else:
            template_yaml = get_template_path(str(template_arg))

    else:
        template_yaml = get_template_path(str(template_arg))

    # Variant
    if args.variant is not None and str(args.variant).strip():
        variant = str(args.variant).strip()
        variant_src = "CLI(--variant)"
    else:
        variant = _derive_variant_from_template_path(Path(template_yaml))
        variant_src = "auto(template)"

    # SLURM defaults + overrides
    slurm_cpu = _slurm_defaults(runtime)

    if args.cpu_partition is not None:
        slurm_cpu["partition"] = args.cpu_partition
    if args.cpu_constraint is not None:
        slurm_cpu["constraint"] = args.cpu_constraint
    if args.cpu_time is not None:
        slurm_cpu["time"] = args.cpu_time
    if args.cpu_mem is not None:
        slurm_cpu["mem"] = args.cpu_mem
    if args.cpu_cpus_per_task is not None:
        slurm_cpu["cpus_per_task"] = args.cpu_cpus_per_task

    try:
        overrides = _parse_overrides(args.override)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    # dry-run preview run_dir
    preview_run_dir = compute_run_dir(
        results_root=results_root,
        beam_model=beam_model,
        sky_model=sky_model,
        variant=variant,
        run_label=run_label,
        run_id=args.run_id,
        unique=unique,
    )

    # Beamcheck arguments
    beamcheck_args: BeamCheckArgs = {}
    if not args.disable_beam_check:
        cfg_beamcheck = _get_nested(runtime, "pyuvsim", "beamcheck") or {}
        check_hours = (
            args.check_hours
            if args.check_hours is not None
            else cfg_beamcheck.get("hours_each_side")
        )
        step_seconds = (
            args.step_seconds
            if args.step_seconds is not None
            else cfg_beamcheck.get("step_seconds")
        )
        beamcheck_env = cfg_beamcheck.get("conda_env")
        if beamcheck_env is not None:
            beamcheck_args = {
                "make_beam_check": True,
                "hours_each_side": check_hours,
                "step_seconds": step_seconds,
                "beamcheck_runner": CondaRunner(
                    conda_activate=conda_sh, env_name=beamcheck_env
                ),
            }
        else:
            print(
                "Beam check requested but no conda_env configured in runtime_paths.yaml."
            )

    if args.dry_run:
        print(
            "\n" + colors.heading("[DRY RUN] Prepare would be executed with:")
        )
        print(
            f"  results_root:       {colors.path(results_root)} "
            f"{colors.source(results_root_src)}"
        )
        print(
            f"  beam_model:         {beam_model} {colors.source(beam_sky_src)}"
        )
        print(
            f"  sky_model:          {sky_model} {colors.source(beam_sky_src)}"
        )
        print(f"  run_id:             {args.run_id}")
        print(
            f"  run_label:          {run_label} {colors.source(run_label_src)}"
        )
        print(f"  unique:             {unique}")
        print(
            f"  template:           {colors.path(template_yaml)} "
            f"{colors.source(template_src)}"
        )
        print(f"  variant:            {variant} {colors.source(variant_src)}")
        if valska_root is not None:
            print(
                f"  valska_root:        {colors.path(valska_root)} "
                f"{colors.source(valska_root_src)}"
            )
        else:
            print("  valska_root:        (none)")
        if beamdata_path is not None:
            print(
                f"  beamdata:           {colors.path(beamdata_path)} "
                f"{colors.source(beamdata_src)}"
            )
        else:
            print("  beamdata:           (none)")
        if args.fwhm_perturb_frac is not None:
            print(f"  fwhm_perturb_frac:  {args.fwhm_perturb_frac:+.6g}")
        else:
            print("  fwhm_perturb_frac:  (none)")
        if repo_path is not None:
            print(
                f"  pyuvsim_repo:       {colors.path(repo_path)} "
                f"{colors.source(repo_src)}"
            )
        else:
            print("  pyuvsim_repo:       (none)")
        print(
            f"  conda:              env={conda_env} {colors.source(conda_src)}"
        )
        print(f"  run_dir (preview):  {colors.path(preview_run_dir)}")
        if beamcheck_args.get("make_beam_check") is not None:
            print(
                "\n"
                + colors.heading("[DRY RUN] Additional beam checks enabled:")
            )
            print(f"  beamcheck conda environment: {beamcheck_env}")
            print(f"  hours each side of transit: {check_hours}")
            print(f"  time step in seconds: {step_seconds}")
        else:
            print(
                "\n"
                + colors.heading("[DRY RUN] Additional beam checks disabled")
            )
        print("\n" + colors.heading("[DRY RUN] SLURM defaults to be written:"))
        print(f"  cpu: {slurm_cpu}")
        print("\n" + colors.success("[DRY RUN] No files will be created."))
        return 0

    install = pyuvsimInstall(install_path=Path(repo_path))
    runner = CondaRunner(conda_activate=conda_sh, env_name=conda_env)

    out = prepare_pyuvsim_run(
        template_yaml=Path(template_yaml),
        install=install,
        runner=runner,
        valska_root=valska_root,
        results_root=Path(results_root),
        beam_model=beam_model,
        sky_model=sky_model,
        variant=variant,
        run_label=run_label,
        run_id=args.run_id,
        run_dir=None,  # single source of truth for canonical path construction
        unique=unique,
        beamdata_path=beamdata_path,
        overrides=overrides,
        slurm_cpu=slurm_cpu,
        fwhm_perturb_frac=args.fwhm_perturb_frac,
        **beamcheck_args,
    )

    run_dir = Path(out["run_dir"])
    manifest = Path(out["manifest_json"])

    print("\n" + colors.heading("Run prepared:"))
    print(f"  run_dir:      {colors.path(run_dir)}")
    print(f"  manifest:     {colors.path(manifest)}")
    print(f"  beam_model:   {beam_model}")
    print(f"  sky_model:    {sky_model}")
    print(f"  variant:      {variant}")
    print(f"  run_label:    {run_label}")
    print(f"  run_id:       {args.run_id}")

    if "submit_sh_beamcheck" in out:
        print("\nAlso prepared 'beam check' run with single source at zenith")

    print("\nNext steps:")
    print("  Option A) Submit via ValSKA (recommended):")
    print(f"     valska-pyuvsim-submit {run_dir}")

    if "submit_sh_simulate" in out:
        print("\n  Option B) Manual submission:")
        print(f"     sbatch {out['submit_sh_simulate']}")
        if "submit_sh_beamcheck" in out:
            print(f"     sbatch {out['submit_sh_beamcheck']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
