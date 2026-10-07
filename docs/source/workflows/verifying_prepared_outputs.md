# Verifying prepared outputs (manifests, jobs, scripts)

Purpose
- Quick reference for the helper scripts that print and inspect files produced by `valska-bayeseor-prepare`.
- Two helper files:
  - `bash_scripts/check_bayeseor_manifests.sh` — runnable checker: runs a prepare into a (temporary by default) `results-root`, prints selected prepared files and performs basic checks (e.g. `manifest["tool"] == "bayeseor"`).
  - `bash_scripts/print_example_prepared_file_outputs.sh` — documentation/example file containing a copy‑pasteable invocation and illustrative sample output.

Prerequisites
- `valska-bayeseor-prepare` on PATH (in your ValSKA environment).
- Optional: `jq` and `yq` for nicer pretty-printing (the scripts fall back to Python / `sed`).

Quick copy‑paste examples

- Default (print manifest only, keep the temporary results-root):
```bash
./bash_scripts/check_bayeseor_manifests.sh --keep \
  --beam chromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data "gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5" \
  --template validation_chromatic_Gaussian.yaml \
  --run-id sweep
```

- Show everything (manifest, jobs.json, submit scripts, YAML templates, artefacts):
```bash
./bash_scripts/check_bayeseor_manifests.sh --show-all --keep \
  --beam chromatic_Gaussian \
  --sky GLEAM \
  --data-root-key gaussian \
  --data "gsm_plus_gleam-158.30-167.10-MHz-..." \
  --template validation_chromatic_Gaussian.yaml \
  --run-id sweep
```

- Reproduce the repo example output:
```bash
# example output is stored in:
# bash_scripts/print_example_prepared_file_outputs.sh
# to reproduce, run the checker with the same args used in that file:
./bash_scripts/check_bayeseor_manifests.sh --show-all --keep <same-args-as-example>
```

What the checker prints (sections)
- manifest — the generated `manifest.json` (pretty-printed).
- jobs — `jobs.json` (if present).
- scripts — SLURM submit scripts / `submit*.sh` / `*.sbatch` (heads).
- yaml — rendered template YAMLs (heads).
- artefacts — files referenced by manifest (heads, textual or marked binary).

CLI options (summary)
- `--keep` : keep the temporary results-root (default temporary dir is removed on exit).
- `--show <list>` : comma-separated list of sections to print (valid: `manifest`, `jobs`, `scripts`, `yaml`, `artefacts`). Default: `manifest`.
- `--show-all` : show all sections.
- `--results-root <dir>` : provide a specific directory to write prepared outputs to (useful for reproducible runs).

Example minimal output (illustrative)
```text
Running: valska-bayeseor-prepare --beam chromatic_Gaussian --sky GLEAM --data-root-key gaussian --data ... --template validation_chromatic_Gaussian.yaml --run-id sweep --results-root <temporary-results-root>

==== Manifest: <temporary-results-root>/.../sweep/manifest.json ====
{
  "tool": "bayeseor",
  "created_utc": "20260125T123456Z",
  "valska_version": "0.1.0",
  "beam_model": "chromatic_Gaussian",
  "sky_model": "GLEAM",
  "run_id": "sweep",
  "run_dir": "<temporary-results-root>/.../sweep",
  "template_name": "validation_chromatic_Gaussian.yaml",
  ...
}
OK: manifest tool is 'bayeseor'

---- jobs.json ----
{ "jobs": [ {"name":"precompute"}, {"name":"fit"} ] }

---- submit.sh (head) ----
#!/bin/sh
#SBATCH --time=1-11:00:00
#SBATCH --mem=64G
srun ./run.sh

---- template YAML (head) ----
priors:
  - name: fwhm

---- artefacts (from manifest) ----
run_script: <temporary-results-root>/.../run.sh
  #!/bin/sh
  echo "ok"

Checked 1 manifest(s) — all OK
Temporary results-root kept at: <temporary-results-root>
```

Exit codes
- 0 : all manifests checked OK
- 2 : no `manifest.json` files found under the results-root
- 3 : one or more manifests failed checks (e.g., wrong `tool`)

Troubleshooting
- No manifest found:
  - Ensure `--data` is a valid relative path under the selected/default data root, or an absolute path to the .uvh5.
  - The checker uses a temporary `--results-root` unless you pass `--results-root <dir>` or `--keep`. Use `--keep` to inspect generated files.
- Wrong `tool` field:
  - Manifest `tool` should be `"bayeseor"`. If it differs, inspect `src/valska/external_tools/bayeseor/setup.py`.
- Pretty printing not working:
  - Install `jq` / `yq`; the scripts fall back to Python / `sed`.
- Binary artefacts:
  - Artefacts are printed head-first and binary files are marked unreadable.

Notes and tips
- `bash_scripts/print_example_prepared_file_outputs.sh` is informational and contains a concrete invocation + sample output — use it to see expected output shape.
- Make the checker executable if needed:
```bash
chmod +x bash_scripts/check_bayeseor_manifests.sh
```
- Consider adding a small CI job that runs the checker with a tiny prepare and verifies `manifest["tool"] == "bayeseor"`.

See also
- `bash_scripts/check_bayeseor_manifests.sh` — checker script
- `bash_scripts/print_example_prepared_file_outputs.sh` — example invocation + sample output
