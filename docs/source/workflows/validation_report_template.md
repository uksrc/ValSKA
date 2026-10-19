# Validation Report Template

This template is a starting point for campaign-level ValSKA validation reports.
It is intended for reports that combine narrative judgement with generated
evidence: figures, tables, JSON summaries, configuration files, and exact
commands.

Final reports should not be text-only. Each major conclusion should point to at
least one produced artefact or an explicit limitation explaining why that
evidence is not yet available.

## Contents

- [Report Metadata](#report-metadata)
- [Executive Summary](#executive-summary)
- [Scope](#scope)
- [Evidence Diagnostics](#evidence-diagnostics)
- [Complete-Analysis Summary](#complete-analysis-summary)
- [Power-Spectrum and Posterior Diagnostics](#power-spectrum-and-posterior-diagnostics)
- [Limitations](#limitations)
- [Conclusions](#conclusions)
- [Appendix A: Inputs](#appendix-a-inputs)
- [Appendix B: Reproducibility Commands](#appendix-b-reproducibility-commands)
- [Appendix C: Campaign Completeness](#appendix-c-campaign-completeness)
- [Appendix D: Assumptions](#appendix-d-assumptions)
- [Appendix E: Artefact Register](#appendix-e-artefact-register)
- [Appendix F: Review Checklist](#appendix-f-review-checklist)

For auditability, the executive summary should briefly reference the appendices
that record inputs, commands, completeness, and assumptions. The details belong
at the end of the document so the main body can focus on the validation
question, evidence, interpretation, and conclusion.

## Report Metadata

| Field | Value |
| --- | --- |
| Report title | `<campaign title>` |
| Campaign identifier | `<run_id or campaign name>` |
| Beam model | `<beam model>` |
| Sky model | `<sky model>` |
| Validation target | `<scientific or technical claim being tested>` |
| Report owner | `<name/team>` |
| Report date | `<YYYY-MM-DD>` |
| ValSKA branch or commit | `<git branch and commit>` |
| External tool versions | `<BayesEoR, Python, relevant environment>` |
| Report status | `draft`, `review`, or `final` |

## Executive Summary

State the validation question, the answer, and the confidence level in a few
short paragraphs.

Recommended content:

- the main conclusion
- whether the campaign passed, failed, or is inconclusive
- the strongest evidence supporting that judgement
- the largest caveat or unresolved risk
- where to find the supporting audit trail, for example: "Inputs,
  reproducibility commands, campaign completeness, and assumptions are recorded
  in [Appendices A-D](#appendix-a-inputs)."

## Scope

Describe what this validation campaign was designed to test.

Include:

- scientific objective
- instrument or analysis component under test
- perturbations or scenarios covered
- scenarios explicitly out of scope
- expected decision enabled by the report

## Evidence Diagnostics

Use evidence diagnostics to show how the signal-fit and no-signal models compare
across the campaign.

Embed the generated evidence plots. In a final campaign report, use paths that
are valid from the report document:

````markdown
```{figure} <relative/path/to/report/delta_log_evidence_vs_perturb_frac.png>
:alt: Delta log evidence versus perturbation fraction
:width: 95%

Delta log evidence as a function of perturbation fraction. Positive values
indicate preference for the signal-fit model.
```
````

````markdown
```{figure} <relative/path/to/report/log_evidence_by_model_vs_perturb_frac.png>
:alt: Log evidence by model versus perturbation fraction
:width: 95%

Log evidence for signal-fit and no-signal hypotheses across the perturbation
sweep.
```
````

Interpretation prompts:

- Where does the evidence prefer the signal-fit model?
- Are positive `Delta ln Z` values expected or spurious for this campaign?
- Is the trend symmetric around the reference perturbation?
- Are there outliers that require inspection of chain health or posterior shape?

## Complete-Analysis Summary

Use the complete-analysis table to summarise pass/fail outcomes for paired
signal/no-signal chains.

Embed the generated successful-results CSV when available:

````markdown
```{csv-table} Complete BayesEoR analysis results
:file: <relative/path/to/report/complete_analysis_successful.csv>
:header-rows: 1
```
````

If the CSV is too wide for the rendered report, include a reduced table:

| Perturbation | Log Bayes factor | Validation | Interpretation |
| --- | ---: | --- | --- |
| `<perturbation>` | `<log BF>` | `PASS` or `FAIL` | `<short interpretation>` |

## Power-Spectrum and Posterior Diagnostics

Use the ValSKA-rendered analysis figure as the primary visual diagnostic for
power-spectrum points and posterior distributions.

````markdown
```{figure} <relative/path/to/report/plot_analysis_results_signal_fit_valska.png>
:alt: ValSKA-rendered BayesEoR signal-fit power spectra and posteriors
:width: 95%

ValSKA-rendered signal-fit power-spectrum and posterior comparison. Classified
non-detections may be omitted from the left-hand spectrum panels by default
because the current chains use log-uniform priors rather than the uniform-prior
runs needed for calibrated upper limits.
```
````

Use the legacy BayesEoR-delegated figure only as a comparison output:

````markdown
```{figure} <relative/path/to/report/plot_analysis_results_signal_fit.png>
:alt: Legacy BayesEoR-delegated signal-fit power spectra and posteriors
:width: 95%

Legacy BayesEoR-delegated figure retained for comparison with the ValSKA-native
renderer.
```
````

Interpretation prompts:

- Which k-bins show posterior mass clearly above the expected noise power?
- Which bins are non-detections or ambiguous under the configured proxy?
- Do posterior shapes change systematically with perturbation?
- Are prior bands visually or statistically influencing the interpretation?
- Are there k-bins requiring a future uniform-prior upper-limit run?

## Limitations

Capture limitations explicitly so that the report remains evidence-based rather
than overstated.

| Limitation | Consequence | Follow-up |
| --- | --- | --- |
| No per-k Bayesian evidence comparison | Detection/non-detection classification is currently a proxy | Consider future per-k model comparison |
| Log-uniform-prior chains used for current posteriors | Non-detections are not calibrated 95 percent upper limits | Run uniform-prior upper-limit chains |
| `<limitation>` | `<consequence>` | `<planned action>` |

## Conclusions

State the campaign conclusion in decision-ready language.

Suggested structure:

- **Conclusion:** `<pass/fail/inconclusive and why>`
- **Evidence basis:** `<figures/tables supporting the conclusion>`
- **Residual risk:** `<main caveat>`
- **Recommended action:** `<accept, rerun, broaden campaign, update model, etc.>`

## Appendix A: Inputs

Document the inputs used to run the campaign.

| Input | Location or identifier | Notes |
| --- | --- | --- |
| Sweep directory | `<path/to/_sweeps/<run_id>>` | Contains `sweep_manifest.json` |
| Runtime paths | `<path/to/runtime_paths.yaml>` | If applicable |
| BayesEoR config | `<path/to/config>` | If applicable |
| Plot config | `<path/to/plot.yaml>` | If customised |
| Data products | `<dataset identifiers>` | UVH5, beam model, sky model, etc. |

## Appendix B: Reproducibility Commands

Record the exact commands used to regenerate the report artefacts.

For the current UKSRC Airy validation sweep:

```bash
python -m valska.external_tools.bayeseor.cli_report \
  validation_results/UKSRC/bayeseor/airy_diam14m/GSM_plus_GLEAM/_sweeps/sweep_airy_init \
  --include-plot-analysis-results \
  --print-complete-analysis-table
```

If one already has the ValSKA environment loaded, the equivalent CLI command is:

```bash
valska-bayeseor-report \
  validation_results/UKSRC/bayeseor/airy_diam14m/GSM_plus_GLEAM/_sweeps/sweep_airy_init \
  --include-plot-analysis-results \
  --print-complete-analysis-table
```

To refresh the report-local figures and tables used by a documentation report,
add an explicit asset export directory:

```bash
valska-bayeseor-report \
  validation_results/UKSRC/bayeseor/airy_diam14m/GSM_plus_GLEAM/_sweeps/sweep_airy_init \
  --include-plot-analysis-results \
  --include-complete-analysis-table \
  --export-report-assets \
  docs/source/reports/<case-study>/<report-id>_assets
```

This writes `artefact_manifest.json` in the asset directory, recording the
source report directory and every copied artefact with portable paths relative
to the sweep or asset directory.

## Appendix C: Campaign Completeness

Summarise how much of the campaign completed successfully before interpreting
the science outputs.

Embed or reference the generated summary table. In a final campaign report, use
the actual report-relative path to the CSV:

````markdown
```{csv-table} Sweep report summary
:file: <relative/path/to/report/sweep_report_summary.csv>
:header-rows: 1
```
````

If the CSV cannot be embedded from the report location, include a compact
manual table:

| Quantity | Value |
| --- | --- |
| Total sweep points | `<n_total>` |
| Complete sweep points | `<n_complete>` |
| Incomplete sweep points | `<n_incomplete>` |
| Evidence source | `ns` or `ins` |
| Notes | `<missing artefacts, failed jobs, exclusions>` |

## Appendix D: Assumptions

List the assumptions that must hold for the interpretation to be valid.

| Assumption | Why it matters | Status |
| --- | --- | --- |
| `<assumption>` | `<impact on validation>` | `accepted`, `tested`, or `open` |

Examples:

- the expected noise power used in plots is appropriate for the campaign
- signal-fit and no-signal chains are paired correctly per perturbation
- incomplete points do not bias the interpretation
- current posterior summaries use log-uniform-prior chains
- non-detections are not calibrated uniform-prior upper limits unless those
  chains have been run

## Appendix E: Artefact Register

List every artefact used in the report.

| Artefact | Role in report | Path |
| --- | --- | --- |
| Sweep summary CSV | Campaign completeness and per-point evidence metrics | `<path>` |
| Sweep summary JSON | Machine-readable report payload | `<path>` |
| Delta log evidence plot | Evidence diagnostic | `<path>` |
| Evidence-by-model plot | Evidence diagnostic | `<path>` |
| ValSKA analysis figure | Power-spectrum/posterior diagnostic | `<path>` |
| Legacy analysis figure | Renderer comparison | `<path>` |
| Complete-analysis CSV | Pass/fail table | `<path>` |
| Complete-analysis JSON | Machine-readable complete-analysis payload | `<path>` |
| Artefact manifest | Source-to-report asset mapping | `<path/to/artefact_manifest.json>` |

## Appendix F: Review Checklist

- [ ] The report states a clear validation question.
- [ ] All figures and tables are generated artefacts or clearly marked manual
      summaries.
- [ ] Figure captions state what conclusion the artefact supports.
- [ ] The report distinguishes detections, non-detections, and calibrated upper
      limits.
- [ ] The evidence source (`ns` or `ins`) is recorded.
- [ ] The ValSKA commit or branch is recorded.
- [ ] Known limitations are not hidden in prose.
- [ ] Reproducibility commands have been run successfully.
