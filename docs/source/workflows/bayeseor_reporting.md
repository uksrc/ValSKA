# BayesEoR reporting workflows (ValSKA)

This page documents the `valska-bayeseor-report` post-processing workflow for completed (or partially completed) sweep directories.

It is designed to work **retroactively** on older sweeps, so you do not need to rerun BayesEoR to generate report artefacts.

Naming conventions used in this page:

- `run_id`: identifier for a sweep campaign
- `sweep_dir`: `_sweeps/<run_id>` directory containing `sweep_manifest.json`
- `run_dir`: one per-point directory listed in the sweep manifest

---

## What this command does

Given a sweep directory containing `sweep_manifest.json`, it can generate:

- sweep summary tables:
  - `sweep_report_summary.csv`
  - `sweep_report_summary.json`
- evidence comparison plots:
  - `delta_log_evidence_vs_perturb_frac.png`
  - `log_evidence_by_model_vs_perturb_frac.png`
- optional extended outputs:
  - `plot_analysis_results_signal_fit.png` (from `BeamAnalysisPlotter.plot_analysis_results`)
  - `plot_analysis_results_signal_fit_valska.png` (from the ValSKA-native BayesEoR plot renderer)
  - `complete_analysis_results.json` and `complete_analysis_successful.csv` (from `run_complete_bayeseor_analysis`)

By default, output files are written under:

```text
<sweep_dir>/report/
```

Plot styling conventions (for publication-quality readability):

- math variables are rendered with LaTeX-style mathtext (for example `$\ln Z$`)
- hypothesis labels use spaced names (`signal fit`, `no signal`) in legends
- in `delta_log_evidence_vs_perturb_frac.png`, points with `\Delta\ln Z > 0`
  are highlighted in red to indicate preference for a spurious detection
- report plots are exported at 300 DPI by default

---

## CLI usage

Basic run (tables + default evidence plots):

```bash
valska-bayeseor-report /path/to/_sweeps/<run_id>
```

Airy sweep helper can trigger this automatically after sweep preparation/submission:

```bash
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-airy_diam14m-GSM_plus_GLEAM_v3.sh --submit all --report
```

Use `--report-no-plots` on the helper for table-only reporting.

For the clean v2 rerun campaign, use the v3 sweep wrappers. They explicitly set
the clean results root to:

```text
validation_results/UKSRC/v2
```

and pass the appropriate named data root (`gaussian` or `airy_diam14m`) to
ValSKA. Activate the ValSKA environment first so the wrapper uses the current
installed `valska-bayeseor-sweep` and `valska-bayeseor-report` entry points:

```bash
conda activate valska
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-airy_diam14m-GSM_plus_GLEAM_v3.sh --dry-run
```

The wrappers default to prepare-only; pass `--submit all` when ready to submit
both CPU and GPU stages:

```bash
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-airy_diam14m-GSM_plus_GLEAM_v3.sh --submit all
```

Gaussian v3 wrappers are available for achromatic and chromatic beams with GSM,
GLEAM, and GSM_plus_GLEAM skies:

```text
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-achromatic_Gaussian-GSM_v3.sh
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-achromatic_Gaussian-GLEAM_v3.sh
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-achromatic_Gaussian-GSM_plus_GLEAM_v3.sh
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-chromatic_Gaussian-GSM_v3.sh
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-chromatic_Gaussian-GLEAM_v3.sh
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-chromatic_Gaussian-GSM_plus_GLEAM_v3.sh
```

JSON summary:

```bash
valska-bayeseor-report /path/to/_sweeps/<run_id> --json
```

Skip evidence plots (tables only):

```bash
valska-bayeseor-report /path/to/_sweeps/<run_id> --no-plots
```

Choose evidence estimator used for ΔlnZ/Bayes factor:

```bash
valska-bayeseor-report /path/to/_sweeps/<run_id> --evidence-source ns
valska-bayeseor-report /path/to/_sweeps/<run_id> --evidence-source ins
```

Enable extended outputs:

```bash
valska-bayeseor-report /path/to/_sweeps/<run_id> \
  --include-plot-analysis-results \
  --include-complete-analysis-table
```

Regenerate the extended report for the UKSRC Airy validation sweep:

```bash
valska-bayeseor-report \
  validation_results/UKSRC/bayeseor/airy_diam14m/GSM_plus_GLEAM/_sweeps/sweep_airy_init \
  --include-plot-analysis-results \
  --include-complete-analysis-table
```

This writes the ValSKA-rendered analysis figure to:

```text
validation_results/UKSRC/bayeseor/airy_diam14m/GSM_plus_GLEAM/_sweeps/sweep_airy_init/report/plot_analysis_results_signal_fit_valska.png
```

Refresh a documentation report's local figure/table assets at the same time:

```bash
valska-bayeseor-report \
  validation_results/UKSRC/bayeseor/airy_diam14m/GSM_plus_GLEAM/_sweeps/sweep_airy_init \
  --include-plot-analysis-results \
  --include-complete-analysis-table \
  --export-report-assets \
  docs/source/reports/hera_beam/uksrc_airy_diam14m_gsm_plus_gleam_sweep_airy_init_assets
```

This copies the generated report artefacts into the chosen asset directory and
writes `artefact_manifest.json` there. The canonical generated outputs still
live under `<sweep_dir>/report/`; the copied assets are a documentation snapshot
for figures, CSV tables, and reviewable report evidence. Paths in the manifest
are relative to the sweep or asset directory so the snapshot is portable.

Print the colourised complete-analysis summary table in the terminal:

```bash
valska-bayeseor-report \
  validation_results/UKSRC/bayeseor/airy_diam14m/GSM_plus_GLEAM/_sweeps/sweep_airy_init \
  --include-plot-analysis-results \
  --print-complete-analysis-table
```

Use plain validation labels and disable colour for ASCII-only logs:

```bash
valska-bayeseor-report \
  validation_results/UKSRC/bayeseor/airy_diam14m/GSM_plus_GLEAM/_sweeps/sweep_airy_init \
  --include-plot-analysis-results \
  --print-complete-analysis-table \
  --complete-analysis-table-style plain \
  --color never
```

Customise the ValSKA-native BayesEoR analysis plot:

```bash
valska-bayeseor-report /path/to/_sweeps/<run_id> \
  --include-plot-analysis-results \
  --plot-config plot.yaml
```

ValSKA ships two plot config files:

```text
src/valska/external_tools/bayeseor/plot_configs/plot.yaml
src/valska/external_tools/bayeseor/plot_configs/default_analysis_plot.yaml
```

When `--plot-config` is omitted, report commands first use `./plot.yaml` if it
exists, then the packaged `plot_configs/plot.yaml` if available, and finally
fall back to built-in defaults. `default_analysis_plot.yaml` is the reference
copy that mirrors the built-in defaults. Minimal
`plot.yaml` example:

```yaml
data:
  hypotheses: both        # signal_fit, no_signal, or both
  cred_interval: 68
  upper_limit_mode: noise_proxy  # noise_proxy, posterior_edge, manual, or off
  upper_limit_plot_mode: omit    # omit or arrow
  uplim_quantile: 0.95
figure:
  suptitle: Custom BayesEoR chain comparison
style:
  colors: ["C0", "C3"]
```

Useful styling controls include:

```yaml
style:
  prior_mode: shared          # shared, grouped, per_chain, or off
  prior_alpha: 0.18
  posterior_plot_priors: true
  posterior_prior_alpha: 0.10
  prior_color: lightsteelblue # named Matplotlib colour or hex colour
  color_mode: perturbation    # perturbation or cycle
  cmap: coolwarm
  format_perturbation_labels: true
```

The plot config also accepts ``prior_colour`` as a YAML alias for
``prior_color``. The default non-detection classifier is a proxy, not a full
per-k Bayesian evidence comparison: ``upper_limit_mode: noise_proxy`` compares
posterior mass with the expected noise power and classifies a bin as a
non-detection when at least ``upper_limit_probability_threshold`` of that mass
lies below the noise level. Because these posteriors currently come from
log-uniform priors rather than the uniform-prior runs needed for calibrated
upper limits, the default ``upper_limit_plot_mode: omit`` hides classified
non-detections from the left-side spectrum and residual panels rather than
drawing upper-limit arrows. Use ``upper_limit_plot_mode: arrow`` only when that
visual convention is wanted for comparison. ``upper_limit_mode: manual`` with
``upper_limit_indices`` gives fully explicit control, ``posterior_edge`` keeps
the simple lower-edge posterior-peak heuristic available for diagnostics, and
``upper_limit_mode: off`` draws every bin as a detection. ``calc_kurtosis``
remains a diagnostic output; it is not used as the sole automatic decision rule
because it measures shape but not where the posterior lies relative to the
noise power or prior.

When `--include-plot-analysis-results` is used, ValSKA keeps the legacy
BayesEoR-delegated comparison PNG and also writes ValSKA-rendered PNGs such as
`plot_analysis_results_signal_fit_valska.png`. The ValSKA-native reader and
renderer port the BSD 3-Clause licensed BayesEoR analysis-plot algorithms so
plot construction can be configured within ValSKA while preserving numerical
parity with BayesEoR chain summaries.

Print the complete-analysis results as a terminal table as well as writing
the JSON and CSV artefacts:

    valska-bayeseor-report /path/to/_sweeps/<run_id> \
      --print-complete-analysis-table

`--print-complete-analysis-table` implies
`--include-complete-analysis-table`. For ASCII-only validation labels, use:

    valska-bayeseor-report /path/to/_sweeps/<run_id> \
      --print-complete-analysis-table \
      --complete-analysis-table-style plain

The standard `--color auto|always|never` option controls terminal styling.
The printing option cannot be combined with `--json`; use
`--include-complete-analysis-table --json` when a machine-readable report
payload is required.

Custom output directory:

```bash
valska-bayeseor-report /path/to/_sweeps/<run_id> \
  --out-dir /path/to/custom_report_dir
```

---

## Wrapper script usage

ValSKA also provides a convenience wrapper:

```bash
bash_scripts/valska-bayeseor-report-sweep.sh --sweep-dir /path/to/_sweeps/<run_id>
```

To discover available sweep directories quickly, use:

```bash
valska-bayeseor-list-sweeps
```

JSON output mode (for scripting):

```bash
valska-bayeseor-list-sweeps --json
```

Filter examples:

```bash
valska-bayeseor-list-sweeps --beam airy_diam14m --sky GSM_plus_GLEAM
valska-bayeseor-list-sweeps --run-id sweep_airy_init --latest
```

Shell helper equivalent:

```bash
bash_scripts/valska-list-sweeps.sh
```

The shell helper is a thin wrapper around `valska-bayeseor-list-sweeps`.

JSON output mode (for scripting):

```bash
bash_scripts/valska-list-sweeps.sh --json
```

---

## Sweep health helpers

For quick, command-local usage examples, run:

```bash
valska-bayeseor-list-sweeps --help
valska-bayeseor-sweep-status --help
valska-bayeseor-validate-sweep --help
valska-bayeseor-sweep-audit --help
```

Check per-point output completeness for a sweep:

```bash
valska-bayeseor-sweep-status /path/to/_sweeps/<run_id>
```

Machine-readable status payload:

```bash
valska-bayeseor-sweep-status /path/to/_sweeps/<run_id> --json
```

Validate sweep integrity with exit-code semantics:

```bash
valska-bayeseor-validate-sweep /path/to/_sweeps/<run_id>
```

Allow partial sweeps (at least one complete point):

```bash
valska-bayeseor-validate-sweep /path/to/_sweeps/<run_id> --allow-partial
```

Require `jobs.json` for every point:

```bash
valska-bayeseor-validate-sweep /path/to/_sweeps/<run_id> --require-jobs-json
```

JSON validation payload (includes `exit_code` and `failures`):

```bash
valska-bayeseor-validate-sweep /path/to/_sweeps/<run_id> --json
```

Aggregate audit across discovered sweeps (list + status + validate):

```bash
valska-bayeseor-sweep-audit
```

Filter and machine-readable output:

```bash
valska-bayeseor-sweep-audit --beam airy_diam14m --sky GSM_plus_GLEAM --json
```

Fail non-zero when any audited sweep is invalid:

```bash
valska-bayeseor-sweep-audit --fail-on-invalid
```

### Wrapper defaults

The wrapper now enables by default:

- standard evidence plots/tables
- `plot_analysis_results` output
- `run_complete_bayeseor_analysis` table/json output

Opt out of extended outputs if needed:

```bash
bash_scripts/valska-bayeseor-report-sweep.sh \
  --sweep-dir /path/to/_sweeps/<run_id> \
  --no-plot-analysis-results \
  --no-complete-analysis-table
```

Skip all plotting:

```bash
bash_scripts/valska-bayeseor-report-sweep.sh \
  --sweep-dir /path/to/_sweeps/<run_id> \
  --no-plots
```

### Environment fallback behaviour

The wrapper will:

1. use `valska-bayeseor-report` directly if available on `PATH`, else
2. fall back to `conda run -n <env> valska-bayeseor-report ...`

Set the conda env name with:

```bash
export VALSKA_CONDA_ENV=valska
```

---

## Handling incomplete sweeps

Reporting is resilient to partial/incomplete points.

If required chain artefacts are missing (for example `data-.txt`), the command does **not** crash the full report. Instead, that point is marked:

- `status: "incomplete"`
- `note: "...Missing chain file..."`

Only complete points are used for computed evidence metrics and extended outputs.

---

## Recommended validation checks

After running a report:

1. confirm `rows_total` and `rows_complete` in JSON output
2. inspect `sweep_report_summary.csv` for per-point status
3. verify expected PNG files exist in the report directory
4. if using extended outputs, check:
   - `plot_analysis_results_signal_fit.png`
   - `complete_analysis_results.json`
   - `complete_analysis_successful.csv`
