"""CLI entrypoint for preparing and optionally submitting BayesEoR sweeps."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

from valska.cli_format import (
    CliColors,
    add_color_argument,
    resolve_color_mode,
)
from valska.external_tools.bayeseor import (
    BayesEoRInstall,
    CondaRunner,
    get_template_path,
)
from valska.utils import (
    get_default_path_manager,
    resolve_data_path_info,
)

from . import sweep as sweep_mod  # for DRY helpers (run_label + point dirs)
from .cli_prepare import _get_nested, _slurm_defaults
from .sweep import run_fwhm_sweep, sweep_root

_STAGE = Literal["none", "cpu", "gpu", "all"]
_HYP = Literal["signal_fit", "no_signal", "both"]
_PERT = Literal["fwhm_deg", "antenna_diameter"]
_SUBMIT_MODE = Literal["per-point", "array"]


def _shell_quote(s: str) -> str:
    """
    Conservative shell quoting for printing copy/paste-ready commands.
    Uses single quotes and escapes embedded single quotes safely.

    Example:
      abc'd -> 'abc'"'"'d'
    """
    if s == "":
        return "''"
    if all(ch.isalnum() or ch in "._/-=+:" for ch in s):
        return s
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _build_rerunnable_sweep_cmd(
    *,
    beam_model: str,
    sky_model: str,
    data_arg: Path,
    data_root_key: str | None,
    run_id: str,
    perturb_parameter: _PERT,
    fwhm_fracs: list[float] | None,
    fwhm_fracs_file: Path | None,
    antenna_diameter_fracs: list[float] | None,
    antenna_diameter_fracs_file: Path | None,
    template_arg: str | None,
    variant: str | None,
    results_root_arg: Path | None,
    bayeseor_repo_arg: Path | None,
    conda_sh_arg: str | None,
    conda_env_arg: str | None,
    overrides: list[str],
    unique: bool,
    hypothesis: str,
    depend_afterok: str | None,
    sbatch_exe: str | None,
    submit_dry_run: bool,
    force: bool,
    resubmit: bool,
    submit_mode: _SUBMIT_MODE,
    array_max_cpu: int | None,
    array_max_gpu: int | None,
    submit_stage: _STAGE,
) -> str:
    """
    Construct a copy/paste-ready valska-bayeseor-sweep command that mirrors user args.
    We intentionally only include flags that are relevant and were explicitly specified
    (or are needed to re-run in the same environment).
    """
    parts: list[str] = ["valska-bayeseor-sweep"]

    # Prefer explicit beam/sky (even if user used deprecated scenario).
    parts += ["--beam", _shell_quote(beam_model)]
    parts += ["--sky", _shell_quote(sky_model)]

    parts += ["--data", _shell_quote(str(data_arg))]
    if data_root_key is not None:
        parts += ["--data-root-key", _shell_quote(data_root_key)]
    parts += ["--run-id", _shell_quote(run_id)]
    parts += ["--perturb-parameter", _shell_quote(perturb_parameter)]

    # Fractions source
    if perturb_parameter == "fwhm_deg":
        if fwhm_fracs is not None:
            parts.append("--fwhm-fracs")
            parts += [_shell_quote(str(x)) for x in fwhm_fracs]
        elif fwhm_fracs_file is not None:
            parts += ["--fwhm-fracs-file", _shell_quote(str(fwhm_fracs_file))]
    elif antenna_diameter_fracs is not None:
        parts.append("--antenna-diameter-fracs")
        parts += [_shell_quote(str(x)) for x in antenna_diameter_fracs]
    elif antenna_diameter_fracs_file is not None:
        parts += [
            "--antenna-diameter-fracs-file",
            _shell_quote(str(antenna_diameter_fracs_file)),
        ]

    # Template / variant
    if template_arg is not None:
        parts += ["--template", _shell_quote(str(template_arg))]
    if variant is not None:
        parts += ["--variant", _shell_quote(str(variant))]

    # Results root (only if explicitly provided)
    if results_root_arg is not None:
        parts += ["--results-root", _shell_quote(str(results_root_arg))]

    # Repo / conda (only if explicitly provided on CLI; runtime_paths.yaml covers otherwise)
    if bayeseor_repo_arg is not None:
        parts += ["--bayeseor-repo", _shell_quote(str(bayeseor_repo_arg))]
    if conda_sh_arg is not None:
        parts += ["--conda-sh", _shell_quote(str(conda_sh_arg))]
    if conda_env_arg is not None:
        parts += ["--conda-env", _shell_quote(str(conda_env_arg))]

    # Overrides
    for ov in overrides:
        parts += ["--override", _shell_quote(ov)]

    # Misc flags
    if unique:
        parts.append("--unique")
    if hypothesis != "both":
        parts += ["--hypothesis", _shell_quote(hypothesis)]
    if depend_afterok is not None:
        parts += ["--depend-afterok", _shell_quote(depend_afterok)]
    if sbatch_exe is not None:
        parts += ["--sbatch-exe", _shell_quote(sbatch_exe)]
    if submit_dry_run:
        parts.append("--submit-dry-run")
    if force:
        parts.append("--force")
    if resubmit:
        parts.append("--resubmit")
    if submit_mode != "per-point":
        parts += ["--submit-mode", _shell_quote(submit_mode)]
    if array_max_cpu is not None:
        parts += ["--array-max-cpu", _shell_quote(str(array_max_cpu))]
    if array_max_gpu is not None:
        parts += ["--array-max-gpu", _shell_quote(str(array_max_gpu))]

    parts += ["--submit", _shell_quote(submit_stage)]

    return " ".join(parts)


def _print_submit_results(submit_results: Any) -> None:
    """
    Pretty-print submit results from sweep_res.submit_results.

    Expected shapes:
      - list[dict] with keys like: run_dir, commands (list[str]), error (str), jobs (dict)
      - anything else: printed via json for debugging
    """
    if not submit_results:
        print("  (no submit_results recorded)")
        return

    def _extract_job_ids(r: dict[str, Any]) -> list[str]:
        """
        Return printable job id lines from a submit result dict (if present).
        We support both:
          - jobs.cpu_precompute.job_id
          - jobs.gpu.{signal_fit,no_signal}.job_id
          - jobs.cpu_precompute_array.job_id
          - jobs.gpu_array.{signal_fit,no_signal}.job_id
        """
        out: list[str] = []
        jobs = r.get("jobs")
        if not isinstance(jobs, dict):
            return out

        cpu_array = jobs.get("cpu_precompute_array")
        if isinstance(cpu_array, dict):
            jid = cpu_array.get("job_id")
            if jid:
                out.append(f"job_id(cpu_precompute_array): {jid}")

        gpu_array = jobs.get("gpu_array")
        if isinstance(gpu_array, dict):
            dep = gpu_array.get("dependency")
            if dep:
                out.append(f"dependency(gpu_array): {dep}")

            sf = gpu_array.get("signal_fit")
            if isinstance(sf, dict):
                jid = sf.get("job_id")
                if jid:
                    out.append(f"job_id(gpu_array:signal_fit): {jid}")

            ns = gpu_array.get("no_signal")
            if isinstance(ns, dict):
                jid = ns.get("job_id")
                if jid:
                    out.append(f"job_id(gpu_array:no_signal): {jid}")

        cpu = jobs.get("cpu_precompute")
        if isinstance(cpu, dict):
            jid = cpu.get("job_id")
            if jid:
                out.append(f"job_id(cpu_precompute): {jid}")

        gpu = jobs.get("gpu")
        if isinstance(gpu, dict):
            dep = gpu.get("dependency")
            if dep:
                out.append(f"dependency(gpu): {dep}")

            sf = gpu.get("signal_fit")
            if isinstance(sf, dict):
                jid = sf.get("job_id")
                if jid:
                    out.append(f"job_id(gpu:signal_fit): {jid}")

            ns = gpu.get("no_signal")
            if isinstance(ns, dict):
                jid = ns.get("job_id")
                if jid:
                    out.append(f"job_id(gpu:no_signal): {jid}")

        return out

    def _is_array_submit_result(r: dict[str, Any]) -> bool:
        if r.get("submit_mode") == "array":
            return True
        if r.get("sweep_dir") or r.get("array_tasks_json"):
            return True
        jobs = r.get("jobs")
        return isinstance(jobs, dict) and (
            "cpu_precompute_array" in jobs or "gpu_array" in jobs
        )

    if isinstance(submit_results, list):
        for r in submit_results:
            if not isinstance(r, dict):
                print(f"  - {r}")
                continue

            is_array = _is_array_submit_result(r)
            if is_array:
                location = r.get("sweep_dir", "<unknown sweep_dir>")
            else:
                location = r.get("run_dir", "<unknown run_dir>")
            stage = r.get("stage", "")
            hyp = r.get("hypothesis", "")
            prefix = f"  - {location}"
            meta = []
            submit_mode = r.get("submit_mode")
            if submit_mode:
                meta.append(f"submit_mode={submit_mode}")
            if stage:
                meta.append(f"stage={stage}")
            if hyp:
                meta.append(f"hyp={hyp}")
            if meta:
                prefix += " [" + ", ".join(meta) + "]"

            print(prefix)

            if is_array:
                for key, label in (
                    ("jobs_json", "jobs_json"),
                    ("array_tasks_json", "array_tasks_json"),
                    ("array_max_cpu", "array_max_cpu"),
                    ("array_max_gpu", "array_max_gpu"),
                ):
                    val = r.get(key)
                    if val is not None:
                        print(f"      {label}: {val}")

            # job ids / dependencies
            for line in _extract_job_ids(r):
                print(f"      {line}")

            if "error" in r:
                print(f"      ERROR: {r['error']}")
                continue

            cmds = r.get("commands")
            if isinstance(cmds, list) and cmds:
                for c in cmds:
                    print(f"      {c}")
            else:
                compact = {
                    k: v
                    for k, v in r.items()
                    if k not in {"run_dir", "sweep_dir"}
                }
                print("      (no commands field; raw result follows)")
                print(
                    "      "
                    + json.dumps(compact, indent=2).replace("\n", "\n      ")
                )
        return

    # unexpected structure
    print("  (submit_results has unexpected type; raw dump)")
    print(json.dumps(submit_results, indent=2))


def _parse_fracs(vals: list[str], *, label: str) -> list[float]:
    """Parse a list of strings into float perturbation values."""
    out: list[float] = []
    for v in vals:
        try:
            out.append(float(v))
        except Exception as e:
            raise ValueError(
                f"ERROR: Could not parse {label} value '{v}' as float: {e}"
            )
    return out


def _parse_fracs_file(path: Path, *, label: str) -> list[float]:
    """
    Parse a text file containing one float per line.

    Supports:
    - blank lines
    - comments starting with '#'
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise ValueError(f"ERROR: {label} file does not exist: {p}")
    lines = p.read_text(encoding="utf-8").splitlines()
    vals: list[str] = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        # allow inline comments: "0.01  # +1%"
        if "#" in s:
            s = s.split("#", 1)[0].strip()
        if s:
            vals.append(s)
    if not vals:
        raise ValueError(
            f"ERROR: No numeric entries found in {label} file: {p}"
        )
    return _parse_fracs(vals, label=label)


def _parse_overrides(kvs: list[str]) -> dict[str, str]:
    """Parse KEY=VALUE override arguments into a dict."""
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


def _derive_variant_from_template_path(template_yaml: Path) -> str:
    """Derive a variant key from a template filename."""
    stem = template_yaml.stem
    if "_template" in stem:
        stem = stem.replace("_template", "", 1)
    return stem.strip("_") or template_yaml.stem


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


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for valska-bayeseor-sweep."""
    p = argparse.ArgumentParser(
        prog="valska-bayeseor-sweep",
        description=(
            "Prepare (and optionally submit) a sweep of BayesEoR runs across "
            "multiple perturbations of a selected beam parameter.\n\n"
            "Sweep output layout:\n"
            "  <results_root>/bayeseor/<beam_model>/<sky_model>/_sweeps/<run_id>/<variant>/<run_label>/\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    p.add_argument(
        "--data",
        type=Path,
        required=True,
        help=(
            "Path to the UVH5 dataset. Relative paths may be resolved via "
            "runtime_paths.yaml:data.named_roots.<key>, "
            "data.named_roots.default, or data.root."
        ),
    )
    p.add_argument(
        "--data-root-key",
        type=str,
        default=None,
        help=(
            "Named root under runtime_paths.yaml:data.named_roots used to "
            "resolve relative --data paths."
        ),
    )

    # New preferred axes
    p.add_argument(
        "--beam",
        type=str,
        default=None,
        help="Beam / instrument model label (e.g. achromatic_Gaussian).",
    )
    p.add_argument(
        "--sky",
        type=str,
        default=None,
        help="Sky model label (e.g. GLEAM, GSM).",
    )

    # Deprecated compatibility
    p.add_argument(
        "--scenario",
        type=str,
        default=None,
        help=(
            "DEPRECATED. Use --beam and --sky.\n"
            "If used, must be '<beam>/<sky>' or '<beam>__<sky>' (e.g. 'achromatic_Gaussian/GLEAM')."
        ),
    )

    p.add_argument(
        "--run-id",
        type=str,
        required=True,
        help="Sweep identifier used as run_id (e.g. sweep_v1). Keeps runs grouped and resumable.",
    )
    p.add_argument(
        "--perturb-parameter",
        choices=["fwhm_deg", "antenna_diameter"],
        default="fwhm_deg",
        help=(
            "Which BayesEoR config key to perturb across sweep points.\n"
            "Default: fwhm_deg."
        ),
    )

    p.add_argument(
        "--fwhm-fracs",
        nargs="+",
        default=None,
        help=(
            "List of fractional FWHM perturbations to run (dimensionless).\n"
            "Example: --fwhm-fracs -0.10 -0.05 ... 0.10\n"
            "Precedence: --fwhm-fracs > --fwhm-fracs-file > runtime_paths.yaml > built-in default."
        ),
    )

    p.add_argument(
        "--fwhm-fracs-file",
        type=Path,
        default=None,
        help=(
            "Path to a text file listing fractional FWHM perturbations (one float per line).\n"
            "Blank lines and '#' comments are ignored.\n"
            "Precedence: --fwhm-fracs > --fwhm-fracs-file > runtime_paths.yaml > built-in default."
        ),
    )
    p.add_argument(
        "--antenna-diameter-fracs",
        nargs="+",
        default=None,
        help=(
            "List of fractional antenna_diameter perturbations to run "
            "(dimensionless).\n"
            "Example: --antenna-diameter-fracs -0.10 -0.05 ... 0.10\n"
            "Precedence: --antenna-diameter-fracs > "
            "--antenna-diameter-fracs-file > runtime_paths.yaml > built-in default."
        ),
    )
    p.add_argument(
        "--antenna-diameter-fracs-file",
        type=Path,
        default=None,
        help=(
            "Path to a text file listing fractional antenna_diameter "
            "perturbations (one float per line).\n"
            "Blank lines and '#' comments are ignored.\n"
            "Precedence: --antenna-diameter-fracs > "
            "--antenna-diameter-fracs-file > runtime_paths.yaml > built-in default."
        ),
    )

    p.add_argument(
        "--results-root",
        type=Path,
        default=None,
        help="Results root. If omitted, resolves via config/runtime_paths.yaml then env/defaults.",
    )

    p.add_argument(
        "--template",
        type=str,
        default=None,
        help=(
            "Template name shipped with ValSKA OR a filesystem path to a template YAML.\n"
            "If omitted, uses bayeseor.default_template from config/runtime_paths.yaml, "
            "otherwise defaults to validation_v1d0_template.yaml."
        ),
    )

    p.add_argument(
        "--variant",
        type=str,
        default=None,
        help=(
            "Template variant key used as a directory level to avoid collisions.\n"
            "If omitted, derived from the selected template filename stem by removing "
            "the first occurrence of '_template'."
        ),
    )

    p.add_argument(
        "--bayeseor-repo",
        type=Path,
        default=None,
        help="Path to local clone of BayesEoR (used to locate scripts/run-analysis.py).",
    )

    p.add_argument(
        "--conda-sh",
        type=str,
        default=None,
        help="Command to source conda.sh in batch jobs.",
    )
    p.add_argument(
        "--conda-env",
        type=str,
        default=None,
        help="Conda env name containing BayesEoR.",
    )

    p.add_argument(
        "--override",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override a top-level YAML key in the template (repeatable).",
    )

    p.add_argument(
        "--unique",
        action="store_true",
        help="Append a UTC timestamp beneath run_label for each point (not recommended for resumable sweeps).",
    )

    # Optional submission orchestration
    p.add_argument(
        "--submit",
        choices=["none", "cpu", "gpu", "all"],
        default="none",
        help="Optionally submit stages after preparing. Default: none.",
    )
    p.add_argument(
        "--submit-mode",
        choices=["per-point", "array"],
        default="per-point",
        help="Submission strategy for sweep jobs. Default: per-point.",
    )
    p.add_argument(
        "--array-max-cpu",
        type=int,
        default=None,
        help="Maximum concurrent CPU array tasks when --submit-mode=array.",
    )
    p.add_argument(
        "--array-max-gpu",
        type=int,
        default=None,
        help="Maximum concurrent GPU array tasks when --submit-mode=array.",
    )
    p.add_argument(
        "--hypothesis",
        choices=["signal_fit", "no_signal", "both"],
        default="both",
        help="Which GPU hypothesis scripts to submit (only used if submit includes GPU). Default: both.",
    )
    p.add_argument(
        "--depend-afterok",
        default=None,
        help="Explicit job id to depend on for GPU submissions (rare; usually per-run recorded CPU job id).",
    )
    p.add_argument(
        "--sbatch-exe",
        default=None,
        help="sbatch executable name/path. Default comes from config/runtime_paths.yaml or 'sbatch'.",
    )
    p.add_argument(
        "--submit-dry-run",
        action="store_true",
        help="Prepare for real, but print sbatch commands only.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Pass through force to submission.",
    )
    p.add_argument(
        "--resubmit",
        action="store_true",
        help=(
            "Resubmit across the sweep (archives each point's jobs.json then requeues).\n"
            "Typical: --submit gpu --resubmit"
        ),
    )

    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run the sweep: print what would be prepared/submitted; do not write files or submit.",
    )

    p.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Print the full sweep result object as JSON.",
    )
    add_color_argument(p)

    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for valska-bayeseor-sweep."""
    args = build_parser().parse_args(argv)

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

    # Resolve data path (supports data.named_roots.<key>, default, and legacy data.root)
    try:
        data_info = resolve_data_path_info(
            args.data, runtime, data_root_key=args.data_root_key
        )
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    data_resolved = data_info.path
    data_src = data_info.source

    # repo_path
    repo_path = args.bayeseor_repo
    if repo_path is None:
        cfg_repo = _get_nested(runtime, "bayeseor", "repo_path")
        if cfg_repo:
            repo_path = Path(str(cfg_repo)).expanduser()
    if repo_path is None and not args.dry_run:
        print(
            "ERROR: BayesEoR repo path not provided. Pass --bayeseor-repo or set bayeseor.repo_path in config/runtime_paths.yaml.",
            file=sys.stderr,
        )
        return 2

    # conda_sh/env
    conda_sh = args.conda_sh
    conda_env = args.conda_env
    if conda_sh is None:
        cfg = _get_nested(runtime, "bayeseor", "conda_sh")
        if cfg:
            conda_sh = str(cfg)
    if conda_env is None:
        cfg = _get_nested(runtime, "bayeseor", "conda_env")
        if cfg:
            conda_env = str(cfg)

    if not args.dry_run:
        if conda_sh is None:
            print(
                "ERROR: conda.sh activation command not provided (set bayeseor.conda_sh or pass --conda-sh).",
                file=sys.stderr,
            )
            return 2
        if conda_env is None:
            print(
                "ERROR: conda env not provided (set bayeseor.conda_env or pass --conda-env).",
                file=sys.stderr,
            )
            return 2

    # template
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

    # variant
    if args.variant is not None and str(args.variant).strip():
        variant = str(args.variant).strip()
        variant_src = "CLI(--variant)"
    else:
        variant = _derive_variant_from_template_path(Path(template_yaml))
        variant_src = "auto(template)"

    perturb_parameter: _PERT = args.perturb_parameter

    # ---- perturbation fracs precedence ----
    fracs: list[float] | None = None

    try:
        if perturb_parameter == "fwhm_deg":
            if (
                args.antenna_diameter_fracs is not None
                or args.antenna_diameter_fracs_file is not None
            ):
                print(
                    "ERROR: --perturb-parameter=fwhm_deg does not allow "
                    "--antenna-diameter-fracs or "
                    "--antenna-diameter-fracs-file.",
                    file=sys.stderr,
                )
                return 2
            if args.fwhm_fracs is not None:
                fracs = _parse_fracs(list(args.fwhm_fracs), label="fwhm frac")
                fracs_src = "CLI(--fwhm-fracs)"
            elif args.fwhm_fracs_file is not None:
                fracs = _parse_fracs_file(
                    Path(args.fwhm_fracs_file), label="fwhm fracs"
                )
                fracs_src = "CLI(--fwhm-fracs-file)"
            else:
                cfg_fracs = _get_nested(
                    runtime, "bayeseor", "sweep", "fwhm_fracs"
                )
                if isinstance(cfg_fracs, list) and cfg_fracs:
                    try:
                        fracs = [float(x) for x in cfg_fracs]
                        fracs_src = (
                            "runtime_paths.yaml(bayeseor.sweep.fwhm_fracs)"
                        )
                    except Exception:
                        fracs = None
                        fracs_src = "default"
                else:
                    fracs_src = "default"
        else:
            if args.fwhm_fracs is not None or args.fwhm_fracs_file is not None:
                print(
                    "ERROR: --perturb-parameter=antenna_diameter does not "
                    "allow --fwhm-fracs or --fwhm-fracs-file.",
                    file=sys.stderr,
                )
                return 2
            if args.antenna_diameter_fracs is not None:
                fracs = _parse_fracs(
                    list(args.antenna_diameter_fracs),
                    label="antenna_diameter frac",
                )
                fracs_src = "CLI(--antenna-diameter-fracs)"
            elif args.antenna_diameter_fracs_file is not None:
                fracs = _parse_fracs_file(
                    Path(args.antenna_diameter_fracs_file),
                    label="antenna_diameter fracs",
                )
                fracs_src = "CLI(--antenna-diameter-fracs-file)"
            else:
                cfg_fracs = _get_nested(
                    runtime,
                    "bayeseor",
                    "sweep",
                    "antenna_diameter_fracs",
                )
                if isinstance(cfg_fracs, list) and cfg_fracs:
                    try:
                        fracs = [float(x) for x in cfg_fracs]
                        fracs_src = (
                            "runtime_paths.yaml("
                            "bayeseor.sweep.antenna_diameter_fracs)"
                        )
                    except Exception:
                        fracs = None
                        fracs_src = "default"
                else:
                    fracs_src = "default"
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    # submission defaults
    sbatch_exe = args.sbatch_exe
    if sbatch_exe is None:
        cfg = _get_nested(runtime, "bayeseor", "submit", "sbatch_exe")
        if isinstance(cfg, str) and cfg.strip():
            sbatch_exe = cfg.strip()
        else:
            sbatch_exe = "sbatch"

    # slurm defaults for scripts (match cli_prepare behaviour)
    slurm_cpu = _slurm_defaults(runtime, "cpu")
    slurm_gpu = _slurm_defaults(runtime, "gpu")

    try:
        overrides_dict = _parse_overrides(args.override)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    if args.dry_run:
        colors = CliColors(
            resolve_color_mode(args.color), enabled=not bool(args.json_out)
        )
        sd = sweep_root(results_root, beam_model, sky_model, args.run_id)
        print("\n" + colors.heading("[DRY RUN] Sweep would be executed with:"))
        print(
            f"  results_root: {colors.path(results_root)} "
            f"{colors.source(results_root_src)}"
        )
        print(f"  beam_model:   {beam_model} {colors.source(beam_sky_src)}")
        print(f"  sky_model:    {sky_model} {colors.source(beam_sky_src)}")
        print(f"  run_id:       {args.run_id}")
        print(f"  sweep_dir:    {colors.path(sd)}")
        print(
            f"  template:     {colors.path(template_yaml)} "
            f"{colors.source(template_src)}"
        )
        print(f"  variant:      {variant} {colors.source(variant_src)}")
        print(
            f"  data:         {colors.path(data_resolved)} "
            f"{colors.source(data_src)}"
        )
        print(f"  perturb_parameter:  {perturb_parameter}")
        if perturb_parameter == "fwhm_deg":
            print(
                "  fwhm_fracs:   "
                f"{fracs if fracs is not None else '(built-in default 9-point set)'} "
                f"{colors.source(fracs_src)}"
            )
        else:
            print(
                "  antenna_diameter_fracs:   "
                f"{fracs if fracs is not None else '(built-in default 9-point set)'} "
                f"{colors.source(fracs_src)}"
            )
        print(f"  unique:       {bool(args.unique)}")
        print(f"  submit:       {args.submit}")
        print(f"  submit_mode:  {args.submit_mode}")
        if args.submit_mode == "array":
            print(f"  array_max_cpu:{args.array_max_cpu}")
            print(f"  array_max_gpu:{args.array_max_gpu}")
        print(f"  sbatch_exe:   {sbatch_exe}")
        print(f"  submit_dry:   {bool(args.submit_dry_run)}")
        print(f"  force:        {bool(args.force)}")
        print(f"  resubmit:     {bool(args.resubmit)}")
        if args.submit != "none":
            print(f"  hypothesis:   {args.hypothesis}")

        # DRY: compute point dirs using sweep.py helpers
        fracs_to_show = (
            fracs if fracs is not None else sweep_mod._default_fwhm_fracs()
        )
        print("\n" + colors.heading("[DRY RUN] Points:"))
        for frac in fracs_to_show:
            run_label = sweep_mod._format_run_label(
                perturb_parameter=perturb_parameter, frac=float(frac)
            )
            base = sweep_mod.sweep_point_dir(
                results_root,
                beam_model,
                sky_model,
                args.run_id,
                variant=variant,
                run_label=run_label,
            )
            run_dir = base / "<UTCSTAMP>" if args.unique else base
            print(
                f"  {float(frac):+0.3f}  {run_label}  ->  "
                f"{colors.path(run_dir)}"
            )

        print(
            "\n"
            + colors.success(
                "[DRY RUN] No files or jobs will be created/submitted."
            )
        )
        return 0

    install = BayesEoRInstall(repo_path=Path(str(repo_path)).expanduser())
    runner = CondaRunner(conda_activate=str(conda_sh), env_name=str(conda_env))

    sweep_res = run_fwhm_sweep(
        template_yaml=template_yaml,
        install=install,
        runner=runner,
        results_root=results_root,
        beam_model=beam_model,
        sky_model=sky_model,
        variant=variant,
        run_id=args.run_id,
        data_path=Path(data_resolved).expanduser(),
        data_path_source=data_src,
        data_root_key=data_info.data_root_key,
        overrides=overrides_dict,
        perturb_parameter=perturb_parameter,
        perturb_fracs=fracs,
        unique=bool(args.unique),
        slurm_cpu=slurm_cpu,
        slurm_gpu=slurm_gpu,
        submit=args.submit,  # type: ignore[arg-type]
        hypothesis=args.hypothesis,  # type: ignore[arg-type]
        depend_afterok=args.depend_afterok,
        sbatch_exe=str(sbatch_exe),
        submit_dry_run=bool(args.submit_dry_run),
        force=bool(args.force),
        resubmit=bool(args.resubmit),
        submit_mode=args.submit_mode,
        array_max_cpu=args.array_max_cpu,
        array_max_gpu=args.array_max_gpu,
        record="jobs.json",
        dry_run=False,
    )

    if args.json_out:
        payload = {
            "results_root": str(sweep_res.results_root),
            "beam_model": sweep_res.beam_model,
            "sky_model": sweep_res.sky_model,
            "variant": sweep_res.variant,
            "run_id": sweep_res.run_id,
            "perturb_parameter": sweep_res.perturb_parameter,
            "data_path": str(sweep_res.data_path),
            "data_path_source": sweep_res.data_path_source,
            "data_root_key": sweep_res.data_root_key,
            "created_utc": sweep_res.created_utc,
            "sweep_dir": str(sweep_res.sweep_dir),
            "sweep_manifest_json": str(sweep_res.sweep_manifest_json),
            "template_yaml": str(sweep_res.template_yaml),
            "submit_mode": sweep_res.submit_mode,
            "sweep_jobs_json": str(sweep_res.sweep_jobs_json)
            if sweep_res.sweep_jobs_json is not None
            else None,
            "array_tasks_json": str(sweep_res.array_tasks_json)
            if sweep_res.array_tasks_json is not None
            else None,
            "points": [
                {
                    "perturb_parameter": p.perturb_parameter,
                    "perturb_frac": p.perturb_frac,
                    "fwhm_perturb_frac": p.perturb_frac
                    if p.perturb_parameter == "fwhm_deg"
                    else None,
                    "antenna_diameter_perturb_frac": p.perturb_frac
                    if p.perturb_parameter == "antenna_diameter"
                    else None,
                    "run_label": p.run_label,
                    "run_dir": str(p.run_dir),
                    "manifest_json": str(p.manifest_json),
                    "jobs_json": str(p.run_dir / "jobs.json")
                    if (p.run_dir / "jobs.json").exists()
                    else None,
                }
                for p in sweep_res.points
            ],
            "submit_results": sweep_res.submit_results,
        }
        print(json.dumps(payload, indent=2))
        return 0

    print("\nSweep prepared:")
    print(f"  sweep_dir:           {sweep_res.sweep_dir}")
    print(f"  sweep_manifest.json: {sweep_res.sweep_manifest_json}")
    print(f"  beam_model:          {sweep_res.beam_model}")
    print(f"  sky_model:           {sweep_res.sky_model}")
    print(f"  variant:             {sweep_res.variant}")
    print(f"  perturb_parameter:   {sweep_res.perturb_parameter}")
    print(f"  points:              {len(sweep_res.points)}")
    print(f"  submit_mode:         {sweep_res.submit_mode}")
    if sweep_res.array_tasks_json is not None:
        print(f"  array_tasks.json:    {sweep_res.array_tasks_json}")
    if sweep_res.sweep_jobs_json is not None:
        print(f"  sweep_jobs.json:     {sweep_res.sweep_jobs_json}")

    did_submit = args.submit != "none"
    if did_submit:
        n_err = sum(
            1
            for r in sweep_res.submit_results
            if isinstance(r, dict) and "error" in r
        )

        print(
            f"  submit:              {args.submit} ({'with errors' if n_err else 'ok'})"
        )
        if n_err:
            print(
                f"  submit_errors:       {n_err} (see sweep_manifest.json submit_results)"
            )

        print("\nSubmission summary:")
        if bool(args.submit_dry_run):
            print(
                "  submit_dry_run: true (no jobs submitted; commands/errors shown below)"
            )
        else:
            print("  submit_dry_run: false (jobs submitted)")

        _print_submit_results(sweep_res.submit_results)

    print("\nPoints:")
    for p in sweep_res.points:
        print(f"  {p.perturb_frac:+.3f}  {p.run_label}  ->  {p.run_dir}")

    # Build copy/paste-ready follow-on commands
    cmd_cpu = _build_rerunnable_sweep_cmd(
        beam_model=beam_model,
        sky_model=sky_model,
        data_arg=args.data,
        data_root_key=args.data_root_key,
        run_id=args.run_id,
        perturb_parameter=perturb_parameter,
        fwhm_fracs=fracs,
        fwhm_fracs_file=args.fwhm_fracs_file,
        antenna_diameter_fracs=fracs,
        antenna_diameter_fracs_file=args.antenna_diameter_fracs_file,
        template_arg=args.template,
        variant=args.variant,
        results_root_arg=args.results_root,
        bayeseor_repo_arg=args.bayeseor_repo,
        conda_sh_arg=args.conda_sh,
        conda_env_arg=args.conda_env,
        overrides=args.override,
        unique=bool(args.unique),
        hypothesis=args.hypothesis,
        depend_afterok=args.depend_afterok,
        sbatch_exe=args.sbatch_exe,
        submit_dry_run=bool(args.submit_dry_run),
        force=bool(args.force),
        resubmit=bool(args.resubmit),
        submit_mode=args.submit_mode,
        array_max_cpu=args.array_max_cpu,
        array_max_gpu=args.array_max_gpu,
        submit_stage="cpu",
    )
    cmd_gpu = _build_rerunnable_sweep_cmd(
        beam_model=beam_model,
        sky_model=sky_model,
        data_arg=args.data,
        data_root_key=args.data_root_key,
        run_id=args.run_id,
        perturb_parameter=perturb_parameter,
        fwhm_fracs=fracs,
        fwhm_fracs_file=args.fwhm_fracs_file,
        antenna_diameter_fracs=fracs,
        antenna_diameter_fracs_file=args.antenna_diameter_fracs_file,
        template_arg=args.template,
        variant=args.variant,
        results_root_arg=args.results_root,
        bayeseor_repo_arg=args.bayeseor_repo,
        conda_sh_arg=args.conda_sh,
        conda_env_arg=args.conda_env,
        overrides=args.override,
        unique=bool(args.unique),
        hypothesis=args.hypothesis,
        depend_afterok=args.depend_afterok,
        sbatch_exe=args.sbatch_exe,
        submit_dry_run=bool(args.submit_dry_run),
        force=bool(args.force),
        resubmit=bool(args.resubmit),
        submit_mode=args.submit_mode,
        array_max_cpu=args.array_max_cpu,
        array_max_gpu=args.array_max_gpu,
        submit_stage="gpu",
    )
    cmd_all = _build_rerunnable_sweep_cmd(
        beam_model=beam_model,
        sky_model=sky_model,
        data_arg=args.data,
        data_root_key=args.data_root_key,
        run_id=args.run_id,
        perturb_parameter=perturb_parameter,
        fwhm_fracs=fracs,
        fwhm_fracs_file=args.fwhm_fracs_file,
        antenna_diameter_fracs=fracs,
        antenna_diameter_fracs_file=args.antenna_diameter_fracs_file,
        template_arg=args.template,
        variant=args.variant,
        results_root_arg=args.results_root,
        bayeseor_repo_arg=args.bayeseor_repo,
        conda_sh_arg=args.conda_sh,
        conda_env_arg=args.conda_env,
        overrides=args.override,
        unique=bool(args.unique),
        hypothesis=args.hypothesis,
        depend_afterok=args.depend_afterok,
        sbatch_exe=args.sbatch_exe,
        submit_dry_run=bool(args.submit_dry_run),
        force=bool(args.force),
        resubmit=bool(args.resubmit),
        submit_mode=args.submit_mode,
        array_max_cpu=args.array_max_cpu,
        array_max_gpu=args.array_max_gpu,
        submit_stage="all",
    )

    # Also build "actual submit" variants (without --submit-dry-run) for next-step guidance.
    cmd_cpu_real = cmd_cpu.replace(" --submit-dry-run", "")
    cmd_gpu_real = cmd_gpu.replace(" --submit-dry-run", "")
    cmd_all_real = cmd_all.replace(" --submit-dry-run", "")

    print("\nNext steps:")

    # Smarter UX:
    # - After CPU submit (real): suggest GPU next, not re-running CPU.
    # - After GPU submit (real): suggest monitoring / submitting remaining points if any.
    # - After submit-dry-run: suggest re-run without submit-dry-run for that stage.
    # - If submit none: show the standard trio.

    if args.submit == "none":
        print("  Option A) Submit via valska-bayeseor-sweep (recommended):")
        print("     # CPU stage across all sweep points:")
        print(f"     {cmd_cpu_real}")
        print(
            "     # GPU stage across all sweep points (after CPU completes):"
        )
        print(f"     {cmd_gpu_real}")
        print("     # Or do both in one go:")
        print(f"     {cmd_all_real}")

    elif args.submit == "cpu":
        print("  Option A) Next step via valska-bayeseor-sweep (recommended):")
        if args.submit_dry_run:
            print(
                "     # You ran a submit dry-run for CPU. To actually submit CPU jobs:"
            )
            print(f"     {cmd_cpu_real}")
            print("     # After CPU jobs finish, submit GPU:")
            print(f"     {cmd_gpu_real}")
        else:
            print(
                "     # CPU jobs submitted. Next: submit GPU once CPU completes successfully:"
            )
            print(f"     {cmd_gpu_real}")
            print(
                "     # If you intended to do both in one go for a fresh sweep, use --submit all next time."
            )

    elif args.submit == "gpu":
        print("  Option A) Next step via valska-bayeseor-sweep (recommended):")
        if args.submit_dry_run:
            print(
                "     # You ran a submit dry-run for GPU. To actually submit GPU jobs:"
            )
            print(f"     {cmd_gpu_real}")
        else:
            print(
                "     # GPU jobs submitted. Typical next step is to monitor jobs:"
            )
            print("     squeue -u $USER")
            print(
                "     # If you want to submit additional points, re-run with the missing perturbation fracs."
            )

    elif args.submit == "all":
        print("  Option A) Next step:")
        if args.submit_dry_run:
            print(
                "     # You ran a submit dry-run for --submit all. To actually submit:"
            )
            print(f"     {cmd_all_real}")
        else:
            print(
                "     # CPU+GPU jobs submitted. Typical next step is to monitor jobs:"
            )
            print("     squeue -u $USER")

    print(
        "\n  Option B) Submit per-point via valska-bayeseor-submit (advanced):"
    )
    print(
        "     # valska-bayeseor-submit expects a run_dir containing manifest.json"
    )
    print("     # CPU stage across sweep:")
    run_label_glob = (
        "fwhm_*" if sweep_res.perturb_parameter == "fwhm_deg" else "antdiam_*"
    )
    print(
        f'     for d in {sweep_res.sweep_dir}/{sweep_res.variant}/{run_label_glob}; do valska-bayeseor-submit "$d" --stage cpu; done'
    )
    print("     # GPU stage across sweep:")
    print(
        f'     for d in {sweep_res.sweep_dir}/{sweep_res.variant}/{run_label_glob}; do valska-bayeseor-submit "$d" --stage gpu; done'
    )

    print("\n  Option C) Manual submission:")
    print("     sbatch <point_run_dir>/submit_cpu_precompute.sh")
    print("     sbatch <point_run_dir>/submit_signal_fit_gpu_run.sh")
    print("     sbatch <point_run_dir>/submit_no_signal_gpu_run.sh")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
