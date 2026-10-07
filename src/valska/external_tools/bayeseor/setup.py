"""Prepare BayesEoR run directories, configs, and submit scripts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from valska.utils_yaml import dump_yaml, load_yaml

from ... import __version__
from . import TOOL_NAME
from .runner import BayesEoRInstall, CondaRunner, ContainerRunner
from .slurm import render_submit_script


def _utc_stamp() -> str:
    """Return a UTC timestamp suitable for directory naming."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


# -----------------------------------------------------------------------------
# YAML IO (ruamel.yaml)
# -----------------------------------------------------------------------------


def _as_flow_seq(seq: Any) -> CommentedSeq:
    """
    Convert a sequence into a flow-style ruamel sequence, and ensure any nested
    sequences also become flow-style. This preserves the compact prior formatting.
    """
    if isinstance(seq, CommentedSeq):
        out = seq
    else:
        out = CommentedSeq(seq)

    out.fa.set_flow_style()
    for i, item in enumerate(list(out)):
        if isinstance(item, (list, tuple, CommentedSeq)):
            inner = (
                item if isinstance(item, CommentedSeq) else CommentedSeq(item)
            )
            inner.fa.set_flow_style()
            out[i] = inner
    return out


# -----------------------------------------------------------------------------
# Template / variant helpers
# -----------------------------------------------------------------------------


def _default_variant_from_template(template_yaml: Path) -> str:
    """
    Derive a stable variant key from a template filename.

    Rules (align with CLI):
      - take filename stem
      - remove first occurrence of "_template" if present
      - strip leading/trailing underscores

    Examples:
      validation_v1d0_template.yaml            -> validation_v1d0
      validation_v1d0_template_achromatic.yaml -> validation_v1d0_achromatic
      validation_achromatic_Gaussian.yaml      -> validation_achromatic_Gaussian
    """
    stem = Path(template_yaml).stem
    stem = stem.replace("_template", "", 1)
    stem = stem.strip("_")
    return stem or Path(template_yaml).stem


# -----------------------------------------------------------------------------
# Config perturbations
# -----------------------------------------------------------------------------


def _apply_fwhm_perturbation(
    cfg: CommentedMap,
    *,
    fwhm_perturb_frac: float | None,
) -> dict[str, Any] | None:
    """
    If provided, apply a multiplicative perturbation to fwhm_deg in the config:
      fwhm_deg <- fwhm_deg * (1 + fwhm_perturb_frac)
    """
    if fwhm_perturb_frac is None:
        return None

    if "fwhm_deg" not in cfg:
        raise KeyError(
            "Cannot apply FWHM perturbation: config has no 'fwhm_deg' key."
        )

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
    }


def _apply_antenna_diameter_perturbation(
    cfg: CommentedMap,
    *,
    antenna_diameter_perturb_frac: float | None,
) -> dict[str, Any] | None:
    """
    If provided, apply a multiplicative perturbation to antenna_diameter:
      antenna_diameter <- antenna_diameter * (1 + antenna_diameter_perturb_frac)
    """
    if antenna_diameter_perturb_frac is None:
        return None

    if "antenna_diameter" not in cfg:
        raise KeyError(
            "Cannot apply antenna diameter perturbation: config has no "
            "'antenna_diameter' key."
        )

    try:
        base = float(cfg["antenna_diameter"])
    except Exception as e:
        raise ValueError(
            "Config 'antenna_diameter' is not numeric: "
            f"{cfg['antenna_diameter']}"
        ) from e

    factor = 1.0 + float(antenna_diameter_perturb_frac)
    new_val = base * factor
    cfg["antenna_diameter"] = new_val

    return {
        "type": "multiplicative",
        "antenna_diameter_base": base,
        "antenna_diameter_perturb_frac": float(antenna_diameter_perturb_frac),
        "factor": factor,
        "antenna_diameter_new": new_val,
    }


# -----------------------------------------------------------------------------
# Hypothesis materialisation
# -----------------------------------------------------------------------------


def _materialise_hypothesis_config(
    base_cfg: CommentedMap,
    *,
    hypothesis: str,
    run_dir: Path,
) -> CommentedMap:
    """
    Create a hypothesis-specific BayesEoR config:
      - sets output_dir under run_dir/output/<hypothesis>
      - selects priors from signal_fit_priors / no_signal_priors (fallback to priors)
      - removes hypothesis-specific prior keys from the rendered config
    """
    if hypothesis not in {"signal_fit", "no_signal"}:
        raise ValueError(
            "hypothesis must be one of: 'signal_fit', 'no_signal'"
        )

    cfg = CommentedMap(base_cfg)

    base_out = run_dir / "output" / hypothesis
    cfg["output_dir"] = str(base_out)

    if hypothesis == "signal_fit":
        pri = cfg.get("signal_fit_priors", cfg.get("priors", None))
        if pri is None:
            raise KeyError(
                "signal_fit hypothesis requested but no priors found "
                "(expected 'signal_fit_priors' or 'priors')."
            )
        cfg["priors"] = _as_flow_seq(pri)
    else:
        pri = cfg.get("no_signal_priors", cfg.get("priors", None))
        if pri is None:
            raise KeyError(
                "no_signal hypothesis requested but no priors found "
                "(expected 'no_signal_priors' or 'priors')."
            )
        cfg["priors"] = _as_flow_seq(pri)

    # Clean up hypothesis-only keys if present
    for k in (
        "signal_fit_priors",
        "no_signal_priors",
        "signal_fit_output_dir",
        "no_signal_output_dir",
    ):
        if k in cfg:
            del cfg[k]

    return cfg


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


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def prepare_bayeseor_run(
    *,
    template_yaml: Path,
    install: BayesEoRInstall,
    runner: CondaRunner | ContainerRunner,
    results_root: Path,
    beam_model: str,
    sky_model: str,
    run_label: str,
    data_path: Path,
    overrides: Mapping[str, Any] | None = None,
    slurm: Mapping[str, object] | None = None,
    slurm_cpu: Mapping[str, object] | None = None,
    slurm_gpu: Mapping[str, object] | None = None,
    run_dir: Path | None = None,
    run_id: str = "default",
    variant: str | None = None,
    unique: bool = False,
    data_path_source: str | None = None,
    data_root_key: str | None = None,
    fwhm_perturb_frac: float | None = None,
    antenna_diameter_perturb_frac: float | None = None,
    hypothesis: str = "both",
) -> dict[str, Path]:
    """
    Prepare a BayesEoR run directory containing hypothesis-specific artefacts.

        Canonical non-sweep layout (when ``run_dir`` is ``None``)::

                <results_root>/bayeseor/<beam_model>/<sky_model>/<variant>/<run_label>/<run_id>[/<UTCSTAMP>]

        The ``variant`` defaults to a value derived from the template filename
        stem (first occurrence of ``_template`` removed). If ``unique=True``, a
        UTC timestamp is appended beneath ``run_id``.

        At most one perturbation mode can be active. ``fwhm_perturb_frac`` applies
        a multiplicative perturbation to ``fwhm_deg``. ``antenna_diameter_perturb_frac``
        applies a multiplicative perturbation to ``antenna_diameter``.

        A single shared CPU precompute script is generated and pointed at an
        available hypothesis config (``signal_fit`` preferred when both are present).

    Returns
    -------
    dict
        Paths to created artefacts (configs, submit scripts, manifest), plus run_dir.
    """
    overrides = dict(overrides or {})
    results_root = Path(results_root).expanduser().resolve()
    template_yaml = Path(template_yaml).expanduser().resolve()
    data_path = Path(data_path).expanduser().resolve()

    beam_model = str(beam_model).strip()
    sky_model = str(sky_model).strip()
    if not beam_model:
        raise ValueError("beam_model must be a non-empty string")
    if not sky_model:
        raise ValueError("sky_model must be a non-empty string")
    if (
        fwhm_perturb_frac is not None
        and antenna_diameter_perturb_frac is not None
    ):
        raise ValueError(
            "Only one perturbation mode may be provided. "
            "Choose either fwhm_perturb_frac or antenna_diameter_perturb_frac."
        )

    # Variant: respect explicit argument; otherwise derive from template filename.
    variant_clean = (variant or "").strip()
    if not variant_clean:
        variant_clean = _default_variant_from_template(template_yaml)

    # Backwards-compatible SLURM handling:
    # If slurm_cpu/slurm_gpu are not supplied, fall back to slurm for both stages.
    if slurm_cpu is None and slurm_gpu is None:
        slurm_cpu = dict(slurm or {})
        slurm_gpu = dict(slurm or {})
    else:
        slurm_cpu = dict(slurm_cpu or {})
        slurm_gpu = dict(slurm_gpu or {})

    # Canonical run_dir (only if not explicitly supplied)
    if run_dir is None:
        base_dir = (
            results_root
            / "bayeseor"
            / beam_model
            / sky_model
            / variant_clean
            / run_label
            / run_id
        )
        run_dir = base_dir / _utc_stamp() if unique else base_dir
    else:
        run_dir = Path(run_dir).expanduser().resolve()

    # Always allow resumable directories (exist_ok=True). "unique" should normally
    # yield a fresh timestamp directory anyway.
    run_dir.mkdir(parents=True, exist_ok=True)

    base_cfg = load_yaml(template_yaml)

    # Required linkage between ValSKA and BayesEoR:
    # Always overwrite any placeholder (e.g. "__SET_BY_VALSKA__").
    base_cfg["data_path"] = str(data_path)

    # Apply perturbation(s) before overrides so overrides can still force a value.
    fwhm_prov = _apply_fwhm_perturbation(
        base_cfg, fwhm_perturb_frac=fwhm_perturb_frac
    )
    ant_diam_prov = _apply_antenna_diameter_perturbation(
        base_cfg,
        antenna_diameter_perturb_frac=antenna_diameter_perturb_frac,
    )

    # Apply simple top-level overrides
    for k, v in overrides.items():
        base_cfg[k] = v

    # Decide which hypotheses to materialise
    if hypothesis == "both":
        hypotheses = ["signal_fit", "no_signal"]
    else:
        hypotheses = [hypothesis]

    # CPU stage uses a single config; prefer signal_fit if present
    cpu_precompute_driver_hypothesis = (
        "signal_fit" if "signal_fit" in hypotheses else hypotheses[0]
    )

    outputs: dict[str, Path] = {"run_dir": run_dir}

    # Write configs + GPU run scripts per hypothesis
    for hyp in hypotheses:
        hyp_cfg = _materialise_hypothesis_config(
            base_cfg, hypothesis=hyp, run_dir=run_dir
        )

        config_yaml = run_dir / f"config_{hyp}.yaml"
        dump_yaml(hyp_cfg, config_yaml)

        submit_gpu = run_dir / f"submit_{hyp}_gpu_run.sh"
        submit_gpu.write_text(
            render_submit_script(
                runner=runner,
                install=install,
                config_yaml=config_yaml,
                run_dir=run_dir,
                slurm=slurm_gpu,
                mode="gpu_run",
            ),
            encoding="utf-8",
        )
        submit_gpu.chmod(0o750)

        outputs[f"config_yaml_{hyp}"] = config_yaml
        outputs[f"submit_sh_{hyp}_gpu_run"] = submit_gpu

    # One shared CPU precompute script (driven by chosen hypothesis config)
    cpu_config_yaml = outputs[
        f"config_yaml_{cpu_precompute_driver_hypothesis}"
    ]
    submit_cpu = run_dir / "submit_cpu_precompute.sh"
    submit_cpu.write_text(
        render_submit_script(
            runner=runner,
            install=install,
            config_yaml=cpu_config_yaml,
            run_dir=run_dir,
            slurm=slurm_cpu,
            mode="cpu",
        ),
        encoding="utf-8",
    )
    submit_cpu.chmod(0o750)
    outputs["submit_sh_cpu_precompute"] = submit_cpu

    # Manifest
    manifest = {
        "tool": TOOL_NAME,
        "created_utc": datetime.now(UTC).isoformat(),
        "valska_version": __version__,
        "beam_model": beam_model,
        "sky_model": sky_model,
        "variant": variant_clean,
        "run_label": run_label,
        "run_id": run_id,
        "results_root": str(results_root),
        "run_dir": str(run_dir),
        "template_yaml": str(template_yaml),
        "template_name": template_yaml.name,
        "data_path": str(data_path),
        "data_path_source": data_path_source,
        "data_root_key": data_root_key,
        "overrides": overrides,
        "hypothesis": hypothesis,
        "slurm": {"cpu": dict(slurm_cpu or {}), "gpu": dict(slurm_gpu or {})},
        "bayeseor": {
            "install": {
                "repo_path": str(install.repo_path),
                "run_script": str(install.run_script),
            },
            "runner": _runner_manifest(runner),
            "fwhm_perturbation": fwhm_prov,
            "antenna_diameter_perturbation": ant_diam_prov,
            "cpu_precompute_driver_hypothesis": cpu_precompute_driver_hypothesis,
        },
        "artefacts": {k: str(v) for k, v in outputs.items() if k != "run_dir"},
    }
    manifest_json = run_dir / "manifest.json"
    manifest_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    outputs["manifest_json"] = manifest_json

    return outputs
