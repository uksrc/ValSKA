"""Tests for standalone BayesEoR sweep report generation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from valska.external_tools.bayeseor import cli_report, evidence
from valska.external_tools.bayeseor.report import (
    _plot_config_for_hypothesis,
    export_report_artefacts,
    generate_sweep_report,
    parse_data_stats_evidence,
)
from valska.external_tools.bayeseor.valska_bayeseor_plotting import (
    BayesEoRPlotConfig,
)

from .constants import mock_read_chains


def _write_data_stats(
    path: Path, *, ns: float, ns_err: str, ins: float, ins_err: str
) -> None:
    path.write_text(
        (
            "Nested Sampling Global Log-Evidence           : "
            f"   {ns:.15E}  +/-    {ns_err}\n"
            "Nested Importance Sampling Global Log-Evidence: "
            f"   {ins:.15E}  +/-    {ins_err}\n"
        ),
        encoding="utf-8",
    )


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
    _write_data_stats(
        signal_stats,
        ns=signal_ns,
        ns_err="1.0E+00",
        ins=signal_ns - 0.2,
        ins_err="5.0E-02",
    )

    no_signal_stats = (
        run_dir / "output" / "no_signal" / "MN-no-signal" / "data-stats.dat"
    )
    no_signal_stats.parent.mkdir(parents=True, exist_ok=True)
    _write_chain_outputs(no_signal_stats.parent)
    _write_data_stats(
        no_signal_stats,
        ns=no_signal_ns,
        ns_err="NaN",
        ins=no_signal_ns - 0.1,
        ins_err="4.0E-02",
    )


def test_parse_data_stats_evidence_reads_ns_and_ins(tmp_path: Path) -> None:
    stats = tmp_path / "data-stats.dat"
    _write_data_stats(
        stats,
        ns=123.4,
        ns_err="2.0E+00",
        ins=122.9,
        ins_err="NaN",
    )

    parsed = parse_data_stats_evidence(stats)
    assert parsed.ns_log_evidence == 123.4
    assert parsed.ns_log_evidence_err == 2.0
    assert parsed.ins_log_evidence == 122.9
    assert parsed.ins_log_evidence_err is None


def test_generate_sweep_report_writes_outputs(tmp_path: Path) -> None:
    sweep_dir = tmp_path / "_sweeps" / "sweep_test"
    point_a = sweep_dir / "validation" / "antdiam_-1.0e-01"
    point_b = sweep_dir / "validation" / "antdiam_0.0e+00"
    _mk_point(point_a, signal_ns=10.0, no_signal_ns=12.0)
    _mk_point(point_b, signal_ns=13.0, no_signal_ns=12.0)

    manifest = {
        "points": [
            {
                "perturb_parameter": "antenna_diameter",
                "perturb_frac": -0.1,
                "run_label": "antdiam_-1.0e-01",
                "run_dir": str(point_a),
            },
            {
                "perturb_parameter": "antenna_diameter",
                "perturb_frac": 0.0,
                "run_label": "antdiam_0.0e+00",
                "run_dir": str(point_b),
            },
        ]
    }
    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "sweep_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result = generate_sweep_report(
        sweep_dir=sweep_dir,
        out_dir=None,
        evidence_source="ins",
        make_plots=False,
    )

    assert result.rows_total == 2
    assert result.rows_complete == 2
    assert result.summary_csv.exists()
    assert result.summary_json.exists()

    summary_csv_bytes = result.summary_csv.read_bytes()
    assert b"\r" not in summary_csv_bytes
    assert summary_csv_bytes.endswith(b"\n")

    payload = json.loads(result.summary_json.read_text(encoding="utf-8"))
    assert len(payload["points"]) == 2
    first = payload["points"][0]
    assert first["status"] == "ok"
    assert first["delta_log_evidence"] is not None
    assert first["run_dir"] == "validation/antdiam_-1.0e-01"
    assert str(tmp_path) not in result.summary_csv.read_text(encoding="utf-8")
    assert str(tmp_path) not in result.summary_json.read_text(encoding="utf-8")


def test_complete_analysis_csv_uses_lf_line_endings_when_empty(
    tmp_path: Path,
) -> None:
    sweep_dir = tmp_path / "_sweeps" / "sweep_test"
    point = sweep_dir / "validation" / "antdiam_0.0e+00"
    _mk_point(point, signal_ns=21.0, no_signal_ns=20.0)
    manifest = {
        "points": [
            {
                "perturb_parameter": "antenna_diameter",
                "perturb_frac": 0.0,
                "run_label": "antdiam_0.0e+00",
                "run_dir": str(point),
            }
        ]
    }
    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "sweep_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    # No anesthetic-readable chain files are present, so the complete
    # analysis produces zero successful results and exercises the
    # empty-table csv.writer branch.
    result = generate_sweep_report(
        sweep_dir=sweep_dir,
        out_dir=None,
        evidence_source="ins",
        make_plots=False,
        include_complete_analysis_table=True,
    )

    assert result.complete_analysis_csv is not None
    raw = result.complete_analysis_csv.read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == 1


def test_complete_analysis_csv_uses_lf_line_endings_when_populated(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(evidence, "read_chains", mock_read_chains)

    sweep_dir = tmp_path / "_sweeps" / "sweep_test"
    point = sweep_dir / "validation" / "antdiam_0.0e+00"
    _mk_point(point, signal_ns=21.0, no_signal_ns=20.0)

    signal_root = point / "output" / "signal_fit" / "MN-signal"
    no_signal_root = point / "output" / "no_signal" / "MN-no-signal"
    (signal_root / "data-").write_text("21.0", encoding="utf-8")
    (no_signal_root / "data-").write_text("20.0", encoding="utf-8")

    manifest = {
        "points": [
            {
                "perturb_parameter": "antenna_diameter",
                "perturb_frac": 0.0,
                "run_label": "antdiam_0.0e+00",
                "run_dir": str(point),
            }
        ]
    }
    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "sweep_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result = generate_sweep_report(
        sweep_dir=sweep_dir,
        out_dir=None,
        evidence_source="ins",
        make_plots=False,
        include_complete_analysis_table=True,
    )

    assert result.complete_analysis_csv is not None
    raw = result.complete_analysis_csv.read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")
    # Header plus at least one successful data row.
    assert raw.count(b"\n") >= 2


def test_export_report_artefacts_copies_outputs_and_writes_manifest(
    tmp_path: Path,
) -> None:
    sweep_dir = tmp_path / "_sweeps" / "sweep_test"
    point = sweep_dir / "validation" / "antdiam_0.0e+00"
    _mk_point(point, signal_ns=21.0, no_signal_ns=20.0)
    manifest = {
        "points": [
            {
                "perturb_parameter": "antenna_diameter",
                "perturb_frac": 0.0,
                "run_label": "antdiam_0.0e+00",
                "run_dir": str(point),
            }
        ]
    }
    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "sweep_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result = generate_sweep_report(
        sweep_dir=sweep_dir,
        out_dir=None,
        evidence_source="ins",
        make_plots=False,
    )
    export = export_report_artefacts(result, tmp_path / "report_assets")

    assert export.manifest_json.exists()
    assert (export.assets_dir / "sweep_report_summary.csv").exists()
    assert (export.assets_dir / "sweep_report_summary.json").exists()
    assert len(export.artefact_paths) == 2

    payload = json.loads(export.manifest_json.read_text(encoding="utf-8"))
    assert payload["sweep_dir"] == "sweep_test"
    assert payload["report_dir"] == "report"
    assert payload["assets_dir"] == "."
    assert payload["rows_complete"] == 1
    roles = {artefact["role"] for artefact in payload["artefacts"]}
    assert roles == {"sweep_summary_csv", "sweep_summary_json"}
    for artefact in payload["artefacts"]:
        assert artefact["source_path"] == f"report/{artefact['name']}"
        assert artefact["copied_path"] == artefact["name"]
    assert str(tmp_path) not in export.manifest_json.read_text(
        encoding="utf-8"
    )


def test_generate_sweep_report_infers_missing_perturb_frac_from_label(
    tmp_path: Path,
) -> None:
    sweep_dir = tmp_path / "_sweeps" / "sweep_test"
    point = sweep_dir / "validation" / "fwhm_-2.0e-01"
    _mk_point(point, signal_ns=10.0, no_signal_ns=12.0)
    manifest = {
        "points": [
            {
                "perturb_parameter": None,
                "perturb_frac": None,
                "run_label": "fwhm_-2.0e-01",
                "run_dir": str(point),
            }
        ]
    }
    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "sweep_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result = generate_sweep_report(
        sweep_dir=sweep_dir,
        out_dir=None,
        evidence_source="ins",
        make_plots=False,
    )

    payload = json.loads(result.summary_json.read_text(encoding="utf-8"))
    row = payload["points"][0]
    assert row["perturb_parameter"] == "fwhm"
    assert row["perturb_frac"] == -0.2


@pytest.mark.parametrize(
    ("legacy_key", "expected_parameter"),
    [
        ("fwhm_perturb_frac", "fwhm_deg"),
        ("antenna_diameter_perturb_frac", "antenna_diameter"),
    ],
)
def test_generate_sweep_report_supports_legacy_perturbation_fields(
    tmp_path: Path,
    legacy_key: str,
    expected_parameter: str,
) -> None:
    sweep_dir = tmp_path / "_sweeps" / "legacy_sweep"
    point = sweep_dir / "validation" / "legacy_1.0e-02"
    _mk_point(point, signal_ns=12.0, no_signal_ns=10.0)

    manifest = {
        "points": [
            {
                legacy_key: 0.01,
                "run_label": "legacy_1.0e-02",
                "run_dir": str(point),
            }
        ]
    }
    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "sweep_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result = generate_sweep_report(
        sweep_dir=sweep_dir,
        out_dir=None,
        evidence_source="ins",
        make_plots=False,
    )

    payload = json.loads(result.summary_json.read_text(encoding="utf-8"))
    row = payload["points"][0]
    assert row["status"] == "ok"
    assert row["perturb_parameter"] == expected_parameter
    assert row["perturb_frac"] == 0.01


def test_cli_report_json_output(tmp_path: Path, capsys) -> None:
    sweep_dir = tmp_path / "_sweeps" / "sweep_test"
    point = sweep_dir / "validation" / "antdiam_0.0e+00"
    _mk_point(point, signal_ns=21.0, no_signal_ns=20.0)

    manifest = {
        "points": [
            {
                "perturb_parameter": "antenna_diameter",
                "perturb_frac": 0.0,
                "run_label": "antdiam_0.0e+00",
                "run_dir": str(point),
            }
        ]
    }
    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "sweep_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    code = cli_report.main([str(sweep_dir), "--json", "--no-plots"])
    assert code == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["rows_total"] == 1
    assert payload["rows_complete"] == 1
    assert payload["valska_plot_analysis_results_pngs"] == []
    assert payload["complete_analysis_rows"] == []


def test_cli_report_can_export_report_assets(
    tmp_path: Path,
    capsys,
) -> None:
    sweep_dir = tmp_path / "_sweeps" / "sweep_test"
    point = sweep_dir / "validation" / "antdiam_0.0e+00"
    _mk_point(point, signal_ns=21.0, no_signal_ns=20.0)
    manifest = {
        "points": [
            {
                "perturb_parameter": "antenna_diameter",
                "perturb_frac": 0.0,
                "run_label": "antdiam_0.0e+00",
                "run_dir": str(point),
            }
        ]
    }
    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "sweep_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    assets_dir = tmp_path / "docs" / "source" / "reports" / "assets"

    code = cli_report.main(
        [
            str(sweep_dir),
            "--json",
            "--no-plots",
            "--export-report-assets",
            str(assets_dir),
        ]
    )
    assert code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["report_assets"]["assets_dir"] == str(assets_dir.resolve())
    assert payload["report_assets"]["artefact_count"] == 2
    assert (assets_dir / "artefact_manifest.json").exists()
    assert (assets_dir / "sweep_report_summary.csv").exists()


def test_default_hypothesis_plot_titles_use_display_labels() -> None:
    config = BayesEoRPlotConfig()

    signal_config = _plot_config_for_hypothesis(config, "signal_fit")
    no_signal_config = _plot_config_for_hypothesis(config, "no_signal")

    assert signal_config.figure.suptitle == "Sweep signal fit chain comparison"
    assert (
        no_signal_config.figure.suptitle == "Sweep no signal chain comparison"
    )


def test_cli_report_progress_always_is_passed_to_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = {}

    def fake_generate_sweep_report(**kwargs):
        calls.update(kwargs)
        return cli_report.SweepReportResult(
            sweep_dir=tmp_path,
            out_dir=tmp_path / "report",
            evidence_source="ins",
            rows_total=1,
            rows_complete=1,
            summary_csv=tmp_path / "report" / "summary.csv",
            summary_json=tmp_path / "report" / "summary.json",
            delta_plot_png=None,
            evidence_plot_png=None,
            plot_analysis_results_png=None,
            valska_plot_analysis_results_pngs=[],
            complete_analysis_json=None,
            complete_analysis_csv=None,
            complete_analysis_rows=[],
        )

    monkeypatch.setattr(
        cli_report,
        "generate_sweep_report",
        fake_generate_sweep_report,
    )

    code = cli_report.main(
        [
            str(tmp_path),
            "--include-complete-analysis-table",
            "--progress",
            "always",
        ]
    )

    assert code == 0
    assert calls["show_progress"] is True


def test_cli_report_prints_color_complete_analysis_table(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    def fake_generate_sweep_report(**kwargs):
        assert kwargs["include_complete_analysis_table"] is True
        return cli_report.SweepReportResult(
            sweep_dir=tmp_path,
            out_dir=tmp_path / "report",
            evidence_source="ins",
            rows_total=2,
            rows_complete=2,
            summary_csv=tmp_path / "report" / "summary.csv",
            summary_json=tmp_path / "report" / "summary.json",
            delta_plot_png=None,
            evidence_plot_png=None,
            plot_analysis_results_png=None,
            valska_plot_analysis_results_pngs=[],
            complete_analysis_json=tmp_path
            / "report"
            / "complete_analysis_results.json",
            complete_analysis_csv=tmp_path
            / "report"
            / "complete_analysis_successful.csv",
            complete_analysis_rows=[
                {
                    "perturbation": "antdiam_1.0e-01",
                    "log_bayes_factor": 3.0,
                    "validation": "FAIL",
                },
                {
                    "perturbation": "antdiam_1.0e-02",
                    "log_bayes_factor": -2.5,
                    "validation": "PASS",
                },
            ],
        )

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(
        cli_report,
        "generate_sweep_report",
        fake_generate_sweep_report,
    )

    code = cli_report.main(
        [
            str(tmp_path),
            "--print-complete-analysis-table",
            "--color",
            "always",
        ]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "\x1b[" in out
    assert "Complete BayesEoR Perturbation Analysis Summary" in out
    assert "ΔD/D = +1.00%" in out
    assert out.index("ΔD/D = +1.00%") < out.index("ΔD/D = +10.00%")
    assert "✅ PASS" in out
    assert "❌ FAIL" in out


def test_cli_report_prints_plain_complete_analysis_table(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    def fake_generate_sweep_report(**kwargs):
        assert kwargs["include_complete_analysis_table"] is True
        return cli_report.SweepReportResult(
            sweep_dir=tmp_path,
            out_dir=tmp_path / "report",
            evidence_source="ins",
            rows_total=1,
            rows_complete=1,
            summary_csv=tmp_path / "report" / "summary.csv",
            summary_json=tmp_path / "report" / "summary.json",
            delta_plot_png=None,
            evidence_plot_png=None,
            plot_analysis_results_png=None,
            valska_plot_analysis_results_pngs=[],
            complete_analysis_json=None,
            complete_analysis_csv=None,
            complete_analysis_rows=[
                {
                    "perturbation": "antdiam_1.0e-02",
                    "log_bayes_factor": -2.5,
                    "validation": "PASS",
                }
            ],
        )

    monkeypatch.setattr(
        cli_report,
        "generate_sweep_report",
        fake_generate_sweep_report,
    )

    code = cli_report.main(
        [
            str(tmp_path),
            "--print-complete-analysis-table",
            "--complete-analysis-table-style",
            "plain",
            "--color",
            "never",
        ]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "\x1b[" not in out
    assert "PASS" in out
    assert "✅ PASS" not in out


def test_cli_report_json_disables_progress(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    calls = {}

    def fake_generate_sweep_report(**kwargs):
        calls.update(kwargs)
        return cli_report.SweepReportResult(
            sweep_dir=tmp_path,
            out_dir=tmp_path / "report",
            evidence_source="ins",
            rows_total=1,
            rows_complete=1,
            summary_csv=tmp_path / "report" / "summary.csv",
            summary_json=tmp_path / "report" / "summary.json",
            delta_plot_png=None,
            evidence_plot_png=None,
            plot_analysis_results_png=None,
            valska_plot_analysis_results_pngs=[],
            complete_analysis_json=None,
            complete_analysis_csv=None,
            complete_analysis_rows=[],
        )

    monkeypatch.setattr(
        cli_report, "generate_sweep_report", fake_generate_sweep_report
    )

    code = cli_report.main(
        [
            str(tmp_path),
            "--include-complete-analysis-table",
            "--progress",
            "always",
            "--json",
        ]
    )

    assert code == 0
    assert calls["show_progress"] is False
    json.loads(capsys.readouterr().out)


def test_cli_report_rejects_print_table_with_json(
    tmp_path: Path,
    capsys,
) -> None:
    code = cli_report.main(
        [str(tmp_path), "--json", "--print-complete-analysis-table"]
    )

    assert code == 2
    assert "cannot be combined with --json" in capsys.readouterr().err


def test_report_extended_plots_include_legacy_and_valska_outputs(
    tmp_path: Path,
) -> None:
    sweep_dir = tmp_path / "_sweeps" / "sweep_test"
    point = sweep_dir / "validation" / "antdiam_0.0e+00"
    _mk_point(point, signal_ns=21.0, no_signal_ns=20.0)
    manifest = {
        "points": [
            {
                "perturb_parameter": "antenna_diameter",
                "perturb_frac": 0.0,
                "run_label": "antdiam_0.0e+00",
                "run_dir": str(point),
            }
        ]
    }
    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "sweep_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result = generate_sweep_report(
        sweep_dir=sweep_dir,
        out_dir=None,
        evidence_source="ins",
        make_plots=False,
        include_plot_analysis_results=True,
    )

    assert result.plot_analysis_results_png is not None
    assert result.plot_analysis_results_png.exists()
    assert len(result.valska_plot_analysis_results_pngs) == 1
    assert result.valska_plot_analysis_results_pngs[0].name == (
        "plot_analysis_results_signal_fit_valska.png"
    )
    assert result.valska_plot_analysis_results_pngs[0].exists()


def test_cli_report_plot_config_can_select_both_hypotheses(
    tmp_path: Path,
    capsys,
) -> None:
    sweep_dir = tmp_path / "_sweeps" / "sweep_test"
    point = sweep_dir / "validation" / "antdiam_0.0e+00"
    _mk_point(point, signal_ns=21.0, no_signal_ns=20.0)
    manifest = {
        "points": [
            {
                "perturb_parameter": "antenna_diameter",
                "perturb_frac": 0.0,
                "run_label": "antdiam_0.0e+00",
                "run_dir": str(point),
            }
        ]
    }
    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "sweep_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    plot_config = tmp_path / "plot.yaml"
    plot_config.write_text(
        "data:\n  hypotheses: both\n  nhistbins: 7\n",
        encoding="utf-8",
    )

    code = cli_report.main(
        [
            str(sweep_dir),
            "--json",
            "--no-plots",
            "--include-plot-analysis-results",
            "--plot-config",
            str(plot_config),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    names = {
        Path(path).name
        for path in payload["valska_plot_analysis_results_pngs"]
    }
    assert names == {
        "plot_analysis_results_signal_fit_valska.png",
        "plot_analysis_results_no_signal_valska.png",
    }
    assert payload["plot_config"] == str(plot_config)


def test_cli_report_uses_cwd_plot_yaml_by_default(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    sweep_dir = tmp_path / "_sweeps" / "sweep_test"
    point = sweep_dir / "validation" / "antdiam_0.0e+00"
    _mk_point(point, signal_ns=21.0, no_signal_ns=20.0)
    manifest = {
        "points": [
            {
                "perturb_parameter": "antenna_diameter",
                "perturb_frac": 0.0,
                "run_label": "antdiam_0.0e+00",
                "run_dir": str(point),
            }
        ]
    }
    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "sweep_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (tmp_path / "plot.yaml").write_text(
        "data:\n  hypotheses: both\n  nhistbins: 7\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    code = cli_report.main(
        [
            str(sweep_dir),
            "--json",
            "--no-plots",
            "--include-plot-analysis-results",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    names = {
        Path(path).name
        for path in payload["valska_plot_analysis_results_pngs"]
    }
    assert names == {
        "plot_analysis_results_signal_fit_valska.png",
        "plot_analysis_results_no_signal_valska.png",
    }
    assert payload["plot_config"] == "plot.yaml"


def test_generate_sweep_report_marks_incomplete_when_chain_file_missing(
    tmp_path: Path,
) -> None:
    sweep_dir = tmp_path / "_sweeps" / "sweep_missing_chain"
    point = sweep_dir / "validation" / "antdiam_0.0e+00"
    _mk_point(point, signal_ns=30.0, no_signal_ns=29.0)

    # Simulate broken/partial run output.
    (point / "output" / "no_signal" / "MN-no-signal" / "data-.txt").unlink()

    manifest = {
        "points": [
            {
                "perturb_parameter": "antenna_diameter",
                "perturb_frac": 0.0,
                "run_label": "antdiam_0.0e+00",
                "run_dir": str(point),
            }
        ]
    }
    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "sweep_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result = generate_sweep_report(
        sweep_dir=sweep_dir,
        out_dir=None,
        evidence_source="ins",
        make_plots=False,
    )

    assert result.rows_total == 1
    assert result.rows_complete == 0

    payload = json.loads(result.summary_json.read_text(encoding="utf-8"))
    assert payload["points"][0]["status"] == "incomplete"
    assert "Missing chain file" in payload["points"][0]["note"]
    assert str(tmp_path) not in payload["points"][0]["note"]
