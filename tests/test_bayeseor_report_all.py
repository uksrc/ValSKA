"""Tests for valska-bayeseor-report-all CLI."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from valska.external_tools.bayeseor import cli_report_all


def _write_chain_outputs(path: Path) -> None:
    np.savetxt(path / "k-vals.txt", np.array([0.1, 0.2]))
    np.savetxt(path / "k-vals-bins.txt", np.array([0.08, 0.15, 0.25]))
    (path / "version.txt").write_text("test-version\n", encoding="utf-8")
    (path / "args.json").write_text(
        json.dumps({"log_priors": True, "priors": [[0.0, 4.0], [0.0, 4.0]]}),
        encoding="utf-8",
    )
    np.savetxt(
        path / "data-.txt",
        np.array(
            [
                [0.10, 0.0, 1.0, 1.2],
                [0.20, 0.0, 1.2, 1.4],
                [0.30, 0.0, 1.4, 1.6],
                [0.25, 0.0, 1.6, 1.8],
                [0.15, 0.0, 1.8, 2.0],
            ]
        ),
    )


def _mk_point(run_dir: Path, *, signal_ns: float, no_signal_ns: float) -> None:
    signal_stats = (
        run_dir / "output" / "signal_fit" / "MN-signal" / "data-stats.dat"
    )
    signal_stats.parent.mkdir(parents=True, exist_ok=True)
    _write_chain_outputs(signal_stats.parent)
    signal_stats.write_text(
        (
            "Nested Sampling Global Log-Evidence           : "
            f"   {signal_ns:.15E}  +/-    1.0E+00\n"
            "Nested Importance Sampling Global Log-Evidence: "
            f"   {signal_ns - 0.1:.15E}  +/-    5.0E-02\n"
        ),
        encoding="utf-8",
    )

    no_signal_stats = (
        run_dir / "output" / "no_signal" / "MN-no-signal" / "data-stats.dat"
    )
    no_signal_stats.parent.mkdir(parents=True, exist_ok=True)
    _write_chain_outputs(no_signal_stats.parent)
    no_signal_stats.write_text(
        (
            "Nested Sampling Global Log-Evidence           : "
            f"   {no_signal_ns:.15E}  +/-    1.0E+00\n"
            "Nested Importance Sampling Global Log-Evidence: "
            f"   {no_signal_ns - 0.1:.15E}  +/-    5.0E-02\n"
        ),
        encoding="utf-8",
    )


def _mk_sweep(
    results_root: Path,
    *,
    beam: str,
    sky: str,
    run_id: str,
    with_points: bool,
) -> Path:
    sweep_dir = results_root / "bayeseor" / beam / sky / "_sweeps" / run_id
    sweep_dir.mkdir(parents=True, exist_ok=True)

    points: list[dict[str, object]] = []
    if with_points:
        point_dir = sweep_dir / "validation" / "antdiam_0.0e+00"
        _mk_point(point_dir, signal_ns=11.0, no_signal_ns=10.5)
        points.append(
            {
                "perturb_parameter": "antenna_diameter",
                "perturb_frac": 0.0,
                "run_label": "antdiam_0.0e+00",
                "run_dir": str(point_dir),
            }
        )

    manifest = {
        "run_id": run_id,
        "beam_model": beam,
        "sky_model": sky,
        "created_utc": "2026-01-01T00:00:00Z",
        "points": points,
    }
    (sweep_dir / "sweep_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return sweep_dir


def test_cli_report_all_json_and_only_new(tmp_path: Path, capsys) -> None:
    results_root = tmp_path / "results"
    sweep_a = _mk_sweep(
        results_root,
        beam="airy_diam14m",
        sky="GSM_plus_GLEAM",
        run_id="sweep_a",
        with_points=True,
    )
    sweep_b = _mk_sweep(
        results_root,
        beam="airy_diam14m",
        sky="GSM_plus_GLEAM",
        run_id="sweep_b",
        with_points=True,
    )

    code = cli_report_all.main(
        ["--results-root", str(results_root), "--json", "--no-plots"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["summary"]["count_discovered"] == 2
    assert payload["summary"]["count_targeted"] == 2
    assert payload["summary"]["count_generated"] == 2
    assert payload["summary"]["count_skipped"] == 0
    assert payload["summary"]["count_errors"] == 0
    assert (sweep_a / "report" / "sweep_report_summary.json").exists()
    assert (sweep_b / "report" / "sweep_report_summary.json").exists()

    code = cli_report_all.main(
        [
            "--results-root",
            str(results_root),
            "--json",
            "--no-plots",
            "--only-new",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["summary"]["count_generated"] == 0
    assert payload["summary"]["count_skipped"] == 2
    assert payload["summary"]["count_errors"] == 0


def test_cli_report_all_color_always(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    results_root = tmp_path / "results"
    _mk_sweep(
        results_root,
        beam="airy_diam14m",
        sky="GSM_plus_GLEAM",
        run_id="sweep_color",
        with_points=True,
    )

    code = cli_report_all.main(
        [
            "--results-root",
            str(results_root),
            "--no-plots",
            "--color",
            "always",
        ]
    )
    assert code == 0

    out = capsys.readouterr().out
    assert "\x1b[" in out
    assert "Sweep batch report summary:" in out
    assert "sweep_color" in out


def test_cli_report_all_fail_on_error_returns_1(
    tmp_path: Path, capsys
) -> None:
    results_root = tmp_path / "results"
    _mk_sweep(
        results_root,
        beam="airy_diam14m",
        sky="GSM_plus_GLEAM",
        run_id="sweep_ok",
        with_points=True,
    )
    _mk_sweep(
        results_root,
        beam="airy_diam14m",
        sky="GSM_plus_GLEAM",
        run_id="sweep_bad",
        with_points=False,
    )

    code = cli_report_all.main(
        [
            "--results-root",
            str(results_root),
            "--json",
            "--no-plots",
            "--fail-on-error",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["summary"]["count_discovered"] == 2
    assert payload["summary"]["count_targeted"] == 2
    assert payload["summary"]["count_generated"] == 1
    assert payload["summary"]["count_errors"] == 1
    assert any(row["status"] == "error" for row in payload["sweeps"])


def test_cli_report_all_propagates_plot_config(
    tmp_path: Path,
    capsys,
) -> None:
    results_root = tmp_path / "results"
    _mk_sweep(
        results_root,
        beam="airy_diam14m",
        sky="GSM_plus_GLEAM",
        run_id="sweep_a",
        with_points=True,
    )
    plot_config = tmp_path / "plot.yaml"
    plot_config.write_text(
        "data:\n  hypotheses: no_signal\n  nhistbins: 7\n",
        encoding="utf-8",
    )

    code = cli_report_all.main(
        [
            "--results-root",
            str(results_root),
            "--json",
            "--no-plots",
            "--include-plot-analysis-results",
            "--plot-config",
            str(plot_config),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    result = payload["sweeps"][0]["result"]
    assert payload["settings"]["plot_config"] == str(plot_config)
    assert result["plot_analysis_results_png"] is not None
    names = {
        Path(path).name for path in result["valska_plot_analysis_results_pngs"]
    }
    assert names == {"plot_analysis_results_no_signal_valska.png"}
