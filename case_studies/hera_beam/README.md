# HERA Beam Case Study

This directory contains campaign-specific scripts for the HERA beam validation
case study. Reusable ValSKA commands and library code remain in the main
package and top-level `bash_scripts/` directory.

The active BayesEoR sweep wrappers are under `bash_scripts/`. Each wrapper
defines one beam and sky combination, then delegates to the shared v3 wrapper
implementation. Run a dry-run before submitting a campaign on a new system:

```bash
case_studies/hera_beam/bash_scripts/valska-bayeseor-sweep-achromatic_Gaussian-GSM_v3.sh \
  --dry-run
```

Earlier wrappers retained for provenance are under
`bash_scripts/archive/pre_v3_20260425/`.

Rendered validation reports and their report-local assets are kept in
`docs/source/reports/hera_beam/` so Sphinx can include them directly.
