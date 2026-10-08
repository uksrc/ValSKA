#!/usr/bin/env python3
"""
Prepare a BayesEoR validation run "kit" under the ValSKA results directory.

This module is the importable CLI entrypoint used by the console script::

  valska-bayeseor-prepare

It preserves the behaviour of the development driver script::

  scripts/prepare_bayeseor_run.py

What this does
--------------
This generates reproducible run artefacts for a BayesEoR analysis, without
actually running BayesEoR itself.

Specifically, it:

- resolves runtime paths (results_root, data root expansion, default template)
- instantiates the BayesEoR runner (currently conda)
- prepares a run directory containing:
  - hypothesis-specific config YAMLs (signal_fit / no_signal)
  - submit scripts for CPU precompute and GPU run stages
  - a manifest.json recording provenance & resolved paths

Design principles
-----------------
- setup.prepare_bayeseor_run() is the single source of truth for canonical
  run_dir construction. This CLI only duplicates run_dir logic for --dry-run
  display.

Variant concept
---------------
We include a <variant> directory level to separate template-level differences
that should never collide (e.g. validation_v1d0 vs
validation_v1d0_achromatic). By default it is derived from the template
filename stem by removing the first occurrence of "_template".

Beam/sky taxonomy
-----------------
The results tree is organised by (beam_model, sky_model), replacing the earlier
overloaded "scenario" label.

Canonical non-sweep run directory::

  <results_root>/bayeseor/<beam_model>/<sky_model>/<variant>/<run_label>/<run_id>[/<UTCSTAMP>]

Backwards compatibility
-----------------------
- --scenario is deprecated. If used, it must be unambiguous:
  - --scenario <beam>/<sky>
  - --scenario <beam>__<sky>
- Any other form (e.g. "GLEAM_beam") is rejected to prevent silent misrouting.

Data path resolution
--------------------
If you pass --data as a relative path, it is resolved using either an explicit
named root from runtime_paths.yaml:data.named_roots (via --data-root-key),
runtime_paths.yaml:data.named_roots.default, or the backwards-compatible
runtime_paths.yaml:data.root if set.

Example runtime_paths.yaml::

  results_root: /share/nas-0-3/psims/validation_results/UKSRC
  data:
    named_roots:
      default: /path/to/default/datasets
      gaussian: /path/to/gaussian/datasets

Then ValSKA will resolve::

  --data foo/bar.uvh5  ->  /path/to/datasets/foo/bar.uvh5

Absolute paths are used as-is. The resolved absolute path is recorded in the
manifest.

Future container support
------------------------
Today this assumes a conda-based runner. In the future we will support
Apptainer/Singularity containers by swapping the "runner" configuration; the
produced run directory, config YAML, and scripts are designed to remain stable.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from valska.cli_format import (
    CliColors,
    add_color_argument,
    resolve_color_mode,
)
from valska.external_tools.bayeseor import (
    BayesEoRInstall,
    CondaRunner,
    get_template_path,
    list_templates,
    prepare_bayeseor_run,
)
from valska.utils import (
    get_default_path_manager,
    resolve_data_path_info,
)


def _utc_stamp() -> str:
    """Return a UTC timestamp suitable for directory naming."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _format_run_label_from_fwhm_frac(frac: float) -> str:
    """Format a run label from a fractional FWHM perturbation."""
    s = f"{frac:+.1e}"
    if s.startswith("+"):
        s = s[1:]
    return f"fwhm_{s}"


def _format_run_label_from_antenna_diameter_frac(frac: float) -> str:
    """Format a run label from a fractional antenna_diameter perturbation."""
    s = f"{frac:+.1e}"
    if s.startswith("+"):
        s = s[1:]
    return f"antdiam_{s}"


def _derive_variant_from_template_path(template_yaml: Path) -> str:
    """
    Derive a stable variant key from a template filename.

    Rules:
      - take filename stem
      - remove first occurrence of "_template" if present

    Examples:
      validation_v1d0_template.yaml            -> validation_v1d0
      validation_v1d0_template_achromatic.yaml -> validation_v1d0_achromatic
      beam_achromatic.yaml                     -> beam_achromatic
    """
    stem = template_yaml.stem
    if "_template" in stem:
        stem = stem.replace("_template", "", 1)
    return stem.strip("_") or template_yaml.stem


def _compute_run_dir(
    *,
    results_root: Path,
    beam_model: str,
    sky_model: str,
    variant: str,
    run_label: str,
    run_id: str,
    unique: bool,
) -> Path:
    """
    Compute the canonical run directory for --dry-run display only.

    NOTE: This duplicates the layout logic used in setup.prepare_bayeseor_run().
    For real prepares we pass run_dir=None so setup.py computes the canonical
    location itself (single source of truth).
    """
    base = (
        results_root
        / "bayeseor"
        / beam_model
        / sky_model
        / variant
        / run_label
        / run_id
    )
    return base / _utc_stamp() if unique else base


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for valska-bayeseor-prepare."""
    parser = argparse.ArgumentParser(
        prog="valska-bayeseor-prepare",
        description=(
            "Prepare a BayesEoR validation run directory.\n\n"
            "Canonical layout:\n"
            "  <results_root>/bayeseor/<beam_model>/<sky_model>/<variant>/<run_label>/<run_id>/\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
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
            "If used, must be '<beam>/<sky>' or '<beam>__<sky>' (e.g. 'achromatic_Gaussian/GLEAM')."
        ),
    )

    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help=(
            "Path to the UVH5 dataset. Relative paths may be resolved via "
            "runtime_paths.yaml:data.named_roots.<key>, "
            "data.named_roots.default, or data.root."
        ),
    )
    parser.add_argument(
        "--data-root-key",
        type=str,
        default=None,
        help=(
            "Named root under runtime_paths.yaml:data.named_roots used to "
            "resolve relative --data paths."
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
            "If omitted, may still be enabled via runtime_paths.yaml (bayeseor.unique_by_default)."
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
            "Note: if the value is negative, use either '--fwhm-perturb-frac=-1e-3' or "
            "place '--' before the value to prevent argparse confusion."
        ),
    )
    parser.add_argument(
        "--antenna-diameter-perturb-frac",
        type=float,
        default=None,
        help=(
            "Apply a multiplicative perturbation to antenna_diameter at "
            "prepare time, specified as a fraction.\n"
            "Example: --antenna-diameter-perturb-frac=-1e-3 means -0.1%% "
            "(multiply by 0.999).\n"
            "Example: --antenna-diameter-perturb-frac=1e-1 means +10%% "
            "(multiply by 1.1).\n"
            "Note: if the value is negative, use either "
            "'--antenna-diameter-perturb-frac=-1e-3' or place '--' before "
            "the value to prevent argparse confusion."
        ),
    )

    parser.add_argument(
        "--template",
        type=str,
        default=None,
        help=(
            "Template name shipped with ValSKA OR a filesystem path to a template YAML.\n"
            "If omitted, uses bayeseor.default_template from config/runtime_paths.yaml, "
            "otherwise defaults to validation_v1d0_template.yaml.\n"
            "To list shipped templates, use --list-templates."
        ),
    )
    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List shipped BayesEoR templates and exit.",
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
            "Optional run label directory component. If not provided and a "
            "perturbation frac is set, a label is automatically generated "
            "(e.g. fwhm_1.0e-02 or antdiam_1.0e-02). "
            "Otherwise defaults to 'default'."
        ),
    )

    parser.add_argument(
        "--bayeseor-repo",
        type=Path,
        default=None,
        help="Path to local clone of BayesEoR (used to locate scripts/run-analysis.py).",
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
        help="Conda env name containing BayesEoR.",
    )

    parser.add_argument(
        "--override",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override a top-level YAML key in the template (repeatable).",
    )

    # SLURM options are primarily configured via runtime_paths.yaml, but we allow overrides.
    parser.add_argument(
        "--cpu-partition",
        type=str,
        default=None,
        help="SLURM partition override for CPU stage.",
    )
    parser.add_argument(
        "--cpu-constraint",
        type=str,
        default=None,
        help="SLURM constraint override for CPU stage.",
    )
    parser.add_argument(
        "--cpu-time",
        type=str,
        default=None,
        help="SLURM time override for CPU stage.",
    )
    parser.add_argument(
        "--cpu-mem",
        type=str,
        default=None,
        help="SLURM mem override for CPU stage.",
    )
    parser.add_argument(
        "--cpu-cpus-per-task",
        type=int,
        default=None,
        help="SLURM cpus-per-task for CPU stage.",
    )

    parser.add_argument(
        "--gpu-partition",
        type=str,
        default=None,
        help="SLURM partition override for GPU stage.",
    )
    parser.add_argument(
        "--gpu-constraint",
        type=str,
        default=None,
        help="SLURM constraint override for GPU stage.",
    )
    parser.add_argument(
        "--gpu-time",
        type=str,
        default=None,
        help="SLURM time override for GPU stage.",
    )
    parser.add_argument(
        "--gpu-mem",
        type=str,
        default=None,
        help="SLURM mem override for GPU stage.",
    )
    parser.add_argument(
        "--gpu-gres",
        type=str,
        default=None,
        help="SLURM gres override for GPU stage.",
    )
    parser.add_argument(
        "--gpu-cpus-per-task",
        type=int,
        default=None,
        help="SLURM cpus-per-task for GPU stage.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved paths and intended run directory, but do not write files.",
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


def _slurm_defaults(runtime: dict[str, Any], profile: str) -> dict[str, Any]:
    """
    Extract SLURM defaults from runtime_paths.yaml.

    Passes through ALL keys from the config to support any SBATCH directive.
    Only truly universal defaults are set here; cluster-specific options
    should be configured in runtime_paths.yaml.
    """
    assert profile in {"cpu", "gpu"}
    key = "slurm_defaults_cpu" if profile == "cpu" else "slurm_defaults_gpu"

    cfg = _get_nested(runtime, "bayeseor", key)
    if not isinstance(cfg, dict):
        cfg = _get_nested(runtime, "bayeseor", "slurm_defaults")
    cfg = cfg if isinstance(cfg, dict) else {}

    # Start with universal defaults (can all be overridden to None in YAML)
    defaults = {
        "time": "12:00:00",
        "mem": "8G",
        "cpus_per_task": 4,
        "nodes": 1,
        "ntasks": 1,
        "ntasks_per_node": 1,
        "job_name_prefix": "bayeseor",
        "mpi": "pmi2",
    }

    # Merge config on top of defaults (config wins, including None to suppress)
    out = {**defaults, **cfg}

    # No more hardcoded gres fallback - let the user configure gpus_per_task OR gres
    # in their runtime_paths.yaml as appropriate for their cluster.

    return out


def _parse_beam_sky(
    *, beam: str | None, sky: str | None, scenario: str | None
) -> tuple[str, str, str]:
    """
    Preferred: --beam and --sky.

    Deprecated: --scenario in the form '<beam>/<sky>' or '<beam>__<sky>'.

    Returns (beam_model, sky_model, source_tag) where source_tag is one of:
      - "CLI(--beam/--sky)"
      - "DEPRECATED(--scenario)"
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
    """CLI entrypoint for valska-bayeseor-prepare."""
    parser = build_parser()
    args = parser.parse_args(argv)
    colors = CliColors(resolve_color_mode(args.color))
    if (
        args.fwhm_perturb_frac is not None
        and args.antenna_diameter_perturb_frac is not None
    ):
        print(
            "ERROR: choose only one perturbation mode. Pass either "
            "--fwhm-perturb-frac or --antenna-diameter-perturb-frac.",
            file=sys.stderr,
        )
        return 2

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
        cfg_unique = _get_nested(runtime, "bayeseor", "unique_by_default")
        if isinstance(cfg_unique, bool):
            unique = cfg_unique

    # data resolution (supports data.named_roots.<key>, default, and legacy data.root)
    try:
        data_info = resolve_data_path_info(
            args.data, runtime, data_root_key=args.data_root_key
        )
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    data_path = data_info.path
    data_src = data_info.source

    # run_label
    if args.run_label is not None and str(args.run_label).strip():
        run_label = str(args.run_label).strip()
        run_label_src = "CLI(--run-label)"
    elif args.fwhm_perturb_frac is not None:
        run_label = _format_run_label_from_fwhm_frac(
            float(args.fwhm_perturb_frac)
        )
        run_label_src = "auto(--fwhm-perturb-frac)"
    elif args.antenna_diameter_perturb_frac is not None:
        run_label = _format_run_label_from_antenna_diameter_frac(
            float(args.antenna_diameter_perturb_frac)
        )
        run_label_src = "auto(--antenna-diameter-perturb-frac)"
    else:
        run_label = "default"
        run_label_src = "default"

    # BayesEoR repo path
    repo_path = args.bayeseor_repo
    repo_src = "CLI"
    if repo_path is None:
        cfg_repo = _get_nested(runtime, "bayeseor", "repo_path")
        if cfg_repo:
            repo_path = Path(str(cfg_repo)).expanduser()
            repo_src = "runtime_paths.yaml"
    if repo_path is None:
        print(
            "ERROR: BayesEoR repo path not provided. Pass --bayeseor-repo or set bayeseor.repo_path in config/runtime_paths.yaml.",
            flush=True,
        )
        return 2

    # conda settings
    conda_sh = args.conda_sh
    conda_env = args.conda_env
    conda_src = "CLI"
    if conda_sh is None:
        cfg = _get_nested(runtime, "bayeseor", "conda_sh")
        if cfg:
            conda_sh = str(cfg)
            conda_src = "runtime_paths.yaml"
    if conda_env is None:
        cfg = _get_nested(runtime, "bayeseor", "conda_env")
        if cfg:
            conda_env = str(cfg)
            conda_src = "runtime_paths.yaml"

    if conda_sh is None or conda_env is None:
        print(
            "ERROR: conda settings not fully specified. Provide --conda-sh and --conda-env or set bayeseor.conda_sh and bayeseor.conda_env in config/runtime_paths.yaml.",
            flush=True,
        )
        return 2

    # Template
    template_arg = args.template
    template_src = "CLI"
    if template_arg is None:
        cfg_t = _get_nested(runtime, "bayeseor", "default_template")
        if cfg_t:
            template_arg = str(cfg_t)
            template_src = "runtime_paths.yaml"
        else:
            template_arg = "validation_v1d0_template.yaml"
            template_src = "default"

    template_path = Path(str(template_arg)).expanduser()
    if template_path.exists():
        template_yaml = template_path
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
    slurm_cpu = _slurm_defaults(runtime, "cpu")
    slurm_gpu = _slurm_defaults(runtime, "gpu")

    # Apply CLI overrides (preserve existing behaviour)
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

    if args.gpu_partition is not None:
        slurm_gpu["partition"] = args.gpu_partition
    if args.gpu_constraint is not None:
        slurm_gpu["constraint"] = args.gpu_constraint
    if args.gpu_time is not None:
        slurm_gpu["time"] = args.gpu_time
    if args.gpu_mem is not None:
        slurm_gpu["mem"] = args.gpu_mem
    if args.gpu_gres is not None:
        slurm_gpu["gres"] = args.gpu_gres
    if args.gpu_cpus_per_task is not None:
        slurm_gpu["cpus_per_task"] = args.gpu_cpus_per_task

    try:
        overrides = _parse_overrides(args.override)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    # dry-run preview run_dir
    preview_run_dir = _compute_run_dir(
        results_root=results_root,
        beam_model=beam_model,
        sky_model=sky_model,
        variant=variant,
        run_label=run_label,
        run_id=args.run_id,
        unique=unique,
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
        print(
            f"  data:               {colors.path(data_path)} "
            f"{colors.source(data_src)}"
        )
        if args.fwhm_perturb_frac is not None:
            print(f"  fwhm_perturb_frac:  {args.fwhm_perturb_frac:+.6g}")
        else:
            print("  fwhm_perturb_frac:  (none)")
        if args.antenna_diameter_perturb_frac is not None:
            print(
                "  antenna_diameter_perturb_frac:  "
                f"{args.antenna_diameter_perturb_frac:+.6g}"
            )
        else:
            print("  antenna_diameter_perturb_frac:  (none)")
        print(
            f"  bayeseor_repo:      {colors.path(repo_path)} "
            f"{colors.source(repo_src)}"
        )
        print(
            f"  conda:              env={conda_env} {colors.source(conda_src)}"
        )
        print(f"  run_dir (preview):  {colors.path(preview_run_dir)}")
        print("\n" + colors.heading("[DRY RUN] SLURM defaults to be written:"))
        print(f"  cpu: {slurm_cpu}")
        print(f"  gpu: {slurm_gpu}")
        print("\n" + colors.success("[DRY RUN] No files will be created."))
        return 0

    install = BayesEoRInstall(repo_path=Path(repo_path))
    runner = CondaRunner(conda_activate=conda_sh, env_name=conda_env)

    out = prepare_bayeseor_run(
        template_yaml=Path(template_yaml),
        install=install,
        runner=runner,
        results_root=Path(results_root),
        beam_model=beam_model,
        sky_model=sky_model,
        variant=variant,
        run_label=run_label,
        run_id=args.run_id,
        run_dir=None,  # single source of truth for canonical path construction
        unique=unique,
        data_path=Path(data_path),
        data_path_source=data_src,
        data_root_key=data_info.data_root_key,
        overrides=overrides,
        slurm_cpu=slurm_cpu,
        slurm_gpu=slurm_gpu,
        fwhm_perturb_frac=args.fwhm_perturb_frac,
        antenna_diameter_perturb_frac=args.antenna_diameter_perturb_frac,
        hypothesis="both",
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

    # ---------------------------------------------------------------------
    # Next steps (recommended submit CLI + manual fallback)
    # ---------------------------------------------------------------------
    print(
        "\n"
        + colors.heading("Next steps (typical BayesEoR two-stage workflow):")
    )

    print("  Option A) Submit via ValSKA (recommended):")
    print(f"     valska-bayeseor-submit {run_dir}")
    print("     # CPU only:")
    print(f"     valska-bayeseor-submit {run_dir} --stage cpu")
    print(
        "     # GPU only (reuses completed CPU outputs if present, otherwise uses a recorded CPU job ID or --depend-afterok):"
    )
    print(f"     valska-bayeseor-submit {run_dir} --stage gpu")
    print(
        "     # If a job hits walltime, you can requeue easily (MultiNest should resume):"
    )
    print(f"     valska-bayeseor-submit {run_dir} --stage gpu --resubmit")

    print(
        "\n"
        + colors.heading(
            "  Option B) Manual submission (inspect scripts, then sbatch):"
        )
    )

    cpu_key = "submit_sh_cpu_precompute"
    if cpu_key in out:
        print("     1) CPU precompute stage (shared):")
        print(f"        sbatch {out[cpu_key]}")

    gpu_cmds: list[str] = []
    for hyp in ("signal_fit", "no_signal"):
        kgpu = f"submit_sh_{hyp}_gpu_run"
        if kgpu in out:
            gpu_cmds.append(f"sbatch {out[kgpu]}")

    if gpu_cmds:
        print(
            "     2) GPU run stage (after CPU stage completes successfully):"
        )
        for c in gpu_cmds:
            print(f"        {c}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
