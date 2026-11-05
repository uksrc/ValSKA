"""Prepare pyuvsim run directories, configs, and submit scripts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from shutil import copytree
from typing import Any

from ruamel.yaml.comments import CommentedMap

from valska.external_tools.pyuvsim.setup_beamcheck import (
    prepare_beam_check_cfg,
)
from valska.utils_yaml import dump_yaml, load_yaml

from ... import __version__
from .constants import TOOL_NAME
from .runner import CondaRunner, ContainerRunner, pyuvsimInstall
from .slurm import render_submit_script
from .templates import get_template_path


def _utc_stamp() -> str:
    """Return a UTC timestamp suitable for directory naming."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _with_valska_root(path_value: Any, valska_root: Path) -> Any:
    """
    Convert a pyuvsim template path to an absolute path under valska_root.

    If path_value is already absolute and contains '/config/pyuvsim/',
    preserve the suffix from 'config/pyuvsim/...'.
    """
    if not isinstance(path_value, str):
        return path_value

    raw = path_value.strip()
    if not raw:
        return path_value

    marker = "config/pyuvsim/"
    normalised = raw.replace("\\\n", "").replace("\n", "").strip()

    if marker in normalised:
        suffix = normalised.split(marker, 1)[1]
        return str((valska_root / marker / suffix).resolve())

    p = Path(normalised).expanduser()
    if p.is_absolute():
        return str(p.resolve())

    return str((valska_root / p).resolve())


def _apply_valska_root_paths(
    cfg: CommentedMap, valska_root: Path
) -> dict[str, Any]:
    """
    Rewrite known pyuvsim file-path fields to absolute paths under valska_root.
    """
    changed: dict[str, Any] = {}

    path_keys = [
        ("sources", "catalog"),
        ("telescope", "array_layout"),
        ("telescope", "telescope_config_name"),
    ]

    for section, key in path_keys:
        sec = cfg.get(section)
        if not isinstance(sec, dict) or key not in sec:
            continue

        old = sec[key]
        new = _with_valska_root(old, valska_root)

        if new != old:
            sec[key] = new
            changed[f"{section}.{key}"] = {
                "old": str(old),
                "new": str(new),
            }

    return changed


# -----------------------------------------------------------------------------
# FWHM perturbation
# -----------------------------------------------------------------------------


def _apply_fwhm_perturbation(
    cfg: CommentedMap,
    *,
    fwhm_perturb_frac: float | None,
) -> dict[str, Any] | None:
    """
    If provided, apply a multiplicative perturbation to fwhm_deg in the config:

      fwhm_deg <- fwhm_deg * (1 + fwhm_perturb_frac)

    If the config does not define fwhm_deg, return a provenance-only record
    noting that no change was applied.
    """
    if fwhm_perturb_frac is None:
        return None

    if "fwhm_deg" not in cfg:
        return {
            "type": "multiplicative",
            "fwhm_perturb_frac": float(fwhm_perturb_frac),
            "applied": False,
            "reason": "config has no 'fwhm_deg' key",
        }

    try:
        base = float(cfg["fwhm_deg"])
    except Exception as e:
        raise ValueError(
            f"Config 'fwhm_deg' is not numeric: {cfg['fwhm_deg']}"
        ) from e

    factor = 1.0 + float(fwhm_perturb_frac)
    new_val = base * factor
    cfg["fwhm_deg"] = new_val

    return {
        "type": "multiplicative",
        "fwhm_deg_base": base,
        "fwhm_perturb_frac": float(fwhm_perturb_frac),
        "factor": factor,
        "fwhm_deg_new": new_val,
        "applied": True,
    }


# -----------------------------------------------------------------------------
# Runner manifest
# -----------------------------------------------------------------------------


def _runner_manifest(runner: CondaRunner | ContainerRunner) -> dict[str, Any]:
    """Return a serializable runner description for the manifest."""
    if isinstance(runner, CondaRunner):
        return {
            "type": "conda",
            "conda_activate": runner.conda_activate,
            "env_name": runner.env_name,
        }
    return {
        "type": "container",
        "apptainer_exe": runner.apptainer_exe,
        "image_path": str(runner.image_path),
        "bind_paths": [str(p) for p in runner.bind_paths],
    }


def _install_manifest(install: pyuvsimInstall | None) -> dict[str, Any] | None:
    """Return a serializable install description for the manifest."""
    if install is None:
        return None

    return {
        "install_path": (
            str(install.install_path)
            if install.install_path is not None
            else None
        ),
        "execution_interface": "pyuvsim.uvsim.run_uvsim",
    }


# -----------------------------------------------------------------------------
# Write outputs
# -----------------------------------------------------------------------------


def _write_simulation(
    *,
    run_dir: Path,
    obsparam_yaml: Path,
    submit_simulate: Path,
    cfg: dict,
    runner: CondaRunner | ContainerRunner,
    install: pyuvsimInstall | None,
    slurm_cpu: Mapping[str, object] | None,
    postprocess_runner: CondaRunner | ContainerRunner = CondaRunner(
        None, None
    ),
    postprocess_cmd: str | None = None,
):
    """
    Write parameters yaml and submit script to run_dir
    for one simulation run.
    """

    dump_yaml(cfg, obsparam_yaml)

    submit_simulate.write_text(
        render_submit_script(
            runner=runner,
            install=install,
            config_yaml=obsparam_yaml,
            run_dir=run_dir,
            slurm=slurm_cpu,
            mode="simulate",
            postprocess_runner=postprocess_runner,
            postprocess_cmd=postprocess_cmd,
        ),
        encoding="utf-8",
    )
    submit_simulate.chmod(0o750)


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def compute_run_dir(
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
    Compute the canonical run directory.
    """
    base_dir = (
        results_root
        / "pyuvsim"
        / beam_model
        / sky_model
        / variant
        / run_label
        / run_id
    )
    return base_dir / _utc_stamp() if unique else base_dir


def prepare_pyuvsim_run(
    *,
    template_yaml: Path,
    install: pyuvsimInstall | None,
    runner: CondaRunner | ContainerRunner,
    results_root: Path,
    beam_model: str,
    sky_model: str,
    run_label: str,
    beamdata_path: Path | None = None,
    valska_root: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    slurm: Mapping[str, object] | None = None,
    slurm_cpu: Mapping[str, object] | None = None,
    run_dir: Path | None = None,
    run_id: str = "default",
    variant: str,
    unique: bool = False,
    fwhm_perturb_frac: float | None = None,
    make_beam_check: bool = False,
    hours_each_side: float | None = None,
    step_seconds: float | None = None,
    beamcheck_runner: CondaRunner | ContainerRunner = CondaRunner(None, None),
) -> dict[str, Path]:
    """
    Prepare a pyuvsim run directory containing a single simulation-stage artefact set.

    Canonical non-sweep layout (when run_dir is None):
      <results_root>/pyuvsim/<beam_model>/<sky_model>/<variant>/<run_label>/<run_id>[/<UTCSTAMP>]

    Returns
    -------
    dict
        Paths to created artefacts (obsparam yaml, submit script, manifest), plus run_dir.
    """

    overrides = dict(overrides or {})
    results_root = Path(results_root).expanduser().resolve()
    template_yaml = Path(template_yaml).expanduser().resolve()
    beamdata_path = (
        Path(beamdata_path).expanduser().resolve()
        if beamdata_path is not None
        else None
    )
    valska_root = (
        Path(valska_root).expanduser().resolve()
        if valska_root is not None
        else None
    )

    beam_model = str(beam_model).strip()
    sky_model = str(sky_model).strip()
    if not beam_model:
        raise ValueError("beam_model must be a non-empty string")
    if not sky_model:
        raise ValueError("sky_model must be a non-empty string")

    # Backwards-compatible SLURM handling:
    # if slurm_cpu is not supplied, fall back to slurm.
    slurm_cpu = dict(slurm_cpu or slurm or {})

    # Canonical run_dir (only if not explicitly supplied)
    if run_dir is None:
        run_dir = compute_run_dir(
            results_root=results_root,
            beam_model=beam_model,
            sky_model=sky_model,
            variant=variant,
            run_label=run_label,
            run_id=run_id,
            unique=unique,
        )
    else:
        run_dir = Path(run_dir).expanduser().resolve()

    run_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_yaml(template_yaml)

    valska_root_rewrites = None
    if valska_root is not None:
        valska_root_rewrites = _apply_valska_root_paths(cfg, valska_root)

    # Optional linkage between ValSKA and pyuvsim:
    # only set beamdata_path if the CLI supplied one.
    if beamdata_path is not None:
        cfg["beamdata_path"] = str(beamdata_path)

    # Apply FWHM perturbation before overrides so overrides can still force a value.
    fwhm_prov = _apply_fwhm_perturbation(
        cfg,
        fwhm_perturb_frac=fwhm_perturb_frac,
    )

    # Apply simple top-level overrides
    for k, v in overrides.items():
        cfg[k] = v

    outputs: dict[str, Path] = {"run_dir": run_dir}
    outputs["obsparam_yaml"] = run_dir / "obsparam.yaml"
    outputs["submit_sh_simulate"] = run_dir / "submit_simulate.sh"

    # Include reference simulation config and catalogue files for the default template
    # TODO: Allow these to be referenced from outside the repository (e.g. a shared data folder)
    # and include them in the manifest
    if template_yaml == get_template_path("fov-19.4-oscar-sm.yml"):
        templates_dir = template_yaml.parent

        for folder in ["telescope_config", "catalog_files"]:
            copytree(
                templates_dir / folder,
                run_dir / folder,
                dirs_exist_ok=True,
            )

    # Prepare the simulation submit script for the main run
    _write_simulation(
        run_dir=run_dir,
        obsparam_yaml=outputs["obsparam_yaml"],
        submit_simulate=outputs["submit_sh_simulate"],
        cfg=cfg,
        runner=runner,
        install=install,
        slurm_cpu=slurm_cpu,
    )

    # If needed prepare the submit script for the zenith test
    if make_beam_check:
        outputs["obsparam_beamcheck_yaml"] = (
            run_dir / "obsparam_beamcheck.yaml"
        )
        outputs["submit_sh_beamcheck"] = run_dir / "submit_beamcheck.sh"

        beam_check_cfg = prepare_beam_check_cfg(
            cfg,
            run_dir,
            template_yaml.parent,
            hours_each_side,
            step_seconds,
        )

        beamcheck_uvh5 = (
            run_dir
            / beam_check_cfg["filing"]["outdir"]
            / (
                f"{beam_check_cfg['filing']['outfile_name']}."
                f"{beam_check_cfg['filing']['output_format']}"
            )
        )
        beamcheck_log_suffix = ".log"
        beamcheck_fig_suffix = ".png"

        # Postprocessing command to run beam diagnostics
        postprocess_cmd = (
            f'valska.beam_metrics "{beamcheck_uvh5}" '
            f'"{outputs["obsparam_beamcheck_yaml"]}" '
            f'--log-suffix "{beamcheck_log_suffix}" '
            f'--fig-suffix "{beamcheck_fig_suffix}"'
        )

        _write_simulation(
            run_dir=run_dir,
            obsparam_yaml=outputs["obsparam_beamcheck_yaml"],
            submit_simulate=outputs["submit_sh_beamcheck"],
            cfg=beam_check_cfg,
            runner=runner,
            install=install,
            slurm_cpu=slurm_cpu,
            postprocess_runner=beamcheck_runner,
            postprocess_cmd=postprocess_cmd,
        )

    # Write final manifest
    manifest = {
        "tool": TOOL_NAME,
        "created_utc": datetime.now(UTC).isoformat(),
        "valska_version": __version__,
        "beam_model": beam_model,
        "sky_model": sky_model,
        "variant": variant,
        "run_label": run_label,
        "run_id": run_id,
        "results_root": str(results_root),
        "run_dir": str(run_dir),
        "template_yaml": str(template_yaml),
        "template_name": template_yaml.name,
        "beam_check": make_beam_check,
        "beamcheck_log_suffix": beamcheck_log_suffix
        if make_beam_check
        else None,
        "beamcheck_fig_suffix": beamcheck_fig_suffix
        if make_beam_check
        else None,
        "beamdata_path": str(beamdata_path)
        if beamdata_path is not None
        else None,
        "valska_root": str(valska_root) if valska_root is not None else None,
        "path_rewrites": valska_root_rewrites,
        "overrides": overrides,
        "slurm": {"cpu": dict(slurm_cpu or {})},
        "pyuvsim": {
            "install": _install_manifest(install),
            "runner": _runner_manifest(runner),
            "fwhm_perturbation": fwhm_prov,
        },
        "artefacts": {k: str(v) for k, v in outputs.items() if k != "run_dir"},
    }

    manifest_json = run_dir / "manifest.json"
    manifest_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    outputs["manifest_json"] = manifest_json

    return outputs
