# Validation Reports

Campaign-specific validation reports can live in this directory once they are
ready to be versioned with the documentation.

Use a case-study subdirectory for each distinct validation programme. For
example, HERA beam reports and their report-local assets live under
`docs/source/reports/hera_beam/`.

Start from the template at:

```text
docs/source/workflows/validation_report_template.md
```

Final reports should embed or directly link the generated figures, CSV tables,
JSON summaries, and commands that support their conclusions.

Use `valska-bayeseor-report --export-report-assets <asset-dir>` to copy the
current generated report artefacts into a documentation asset directory and
write an `artefact_manifest.json` describing where each copied file came from.
Manifest source paths are relative to the sweep directory, and copied paths
are relative to the asset directory. The canonical generated outputs remain
under the sweep's `report/` directory.
