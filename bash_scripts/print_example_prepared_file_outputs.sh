#!/usr/bin/env bash
# Quick helper: run valska-bayeseor-prepare into a temp results-root, print selected files found under the run dir(s),
# and perform a basic check that manifest.tool == "bayeseor".
#
# Usage:
#   ./bash_scripts/print_example_prepared_file_outputs.sh [--keep] [--show <list>] [--show-all] <valska-bayeseor-prepare args...>
#
# Examples:
#   # default: print only manifest (and check tool field)
#   ./bash_scripts/print_example_prepared_file_outputs.sh --beam chromatic_Gaussian --sky GLEAM --data-root-key gaussian --data "<data-file>" --template validation_chromatic_Gaussian.yaml --run-id sweep
#
#   # show manifest + jobs.json + submit scripts + yaml + artefacts
#   ./bash_scripts/print_example_prepared_file_outputs.sh --show manifest,jobs,scripts,yaml,artefacts ...
#
#   # convenience: show all
#   ./bash_scripts/print_example_prepared_file_outputs.sh --show-all ...
#
#   # keep the temporary results root for inspection
#   ./bash_scripts/print_example_prepared_file_outputs.sh --keep ...
#
# Exact example (copy-pastable)
#
# Command:
#   ./bash_scripts/print_example_prepared_file_outputs.sh --keep \
#     --beam chromatic_Gaussian \
#     --sky GLEAM \
#     --data-root-key gaussian \
#     --data "gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5" \
#     --template validation_chromatic_Gaussian.yaml \
#     --run-id sweep
#
# Example output (paths & timestamps will vary):
#
# Running: valska-bayeseor-prepare --beam chromatic_Gaussian --sky GLEAM --data-root-key gaussian --data ... --template validation_chromatic_Gaussian.yaml --run-id sweep --results-root <temporary-results-root>
#
# ==== Manifest: <temporary-results-root>/bayeseor/chromatic_Gaussian/GLEAM/validation_chromatic_Gaussian/default/sweep/manifest.json ====
# {
#   "tool": "bayeseor",
#   "created_utc": "20260125T123456Z",
#   "valska_version": "0.1.0",
#   "beam_model": "chromatic_Gaussian",
#   "sky_model": "GLEAM",
#   "variant": "validation_chromatic_Gaussian",
#   "run_label": "default",
#   "run_id": "sweep",
#   "results_root": "<temporary-results-root>",
#   "run_dir": "<temporary-results-root>/.../sweep",
#   "template_name": "validation_chromatic_Gaussian.yaml",
#   "data_path": "<data-root>/gsm_plus_gleam-158...uvh5",
#   "hypothesis": "both",
#   "bayeseor": {"install": {"repo_path": "<bayeseor-repo>", "run_script": "run.sh"}},
#   "artefacts": {"run_script": "<temporary-results-root>/.../run.sh"}
# }
# OK: manifest tool is 'bayeseor'
#
# ---- jobs.json ----
# {
#   "jobs": [
#     {"name": "precompute", "script": "precompute.sh"},
#     {"name": "fit", "script": "fit.sh", "depends_on": ["precompute"]}
#   ]
# }
#
# ---- submit.sh (head) ----
# #!/bin/sh
# #SBATCH --time=1-11:00:00
# #SBATCH --mem=64G
# srun ./run.sh
#
# ---- validation_chromatic_Gaussian.yaml (head) ----
# priors:
#   - name: fwhm
#     prior: ...
#
# ---- artefacts (from manifest) ----
# run_script: /tmp/.../run.sh
#   #!/bin/sh
#   echo "ok"
#
# Checked 1 manifest(s) — all OK


set -euo pipefail

KEEP=0
SHOW_LIST=()
SHOW_ALL=0
ARGS=()

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
TMP_PARENT="${VALSKA_TMPDIR:-$PROJECT_ROOT/temp/tmp}"

usage() {
  cat <<USAGE
Usage: $0 [--keep] [--show <list>] [--show-all] -- <valska-bayeseor-prepare args...>

Options:
  --keep            Keep the temporary results-root (do not remove).
  --show <list>     Comma-separated list of sections to print. Valid: manifest,jobs,scripts,yaml,artefacts
                    Can be repeated. Default (if not provided): manifest
  --show-all        Shortcut to show all sections.
  -h, --help        Show this help and exit.
USAGE
}

# parse our options; forward any other args to valska-bayeseor-prepare
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep) KEEP=1; shift ;;
    --show)
      if [[ -z "${2-}" ]]; then
        echo "Missing argument for --show" >&2; usage; exit 1
      fi
      s="$2"; shift 2
      IFS=',' read -r -a items <<< "$s"
      for it in "${items[@]}"; do SHOW_LIST+=("$(echo "$it" | tr '[:upper:]' '[:lower:]' | xargs)"); done
      ;;
    --show=*)
      s="${1#--show=}"; shift
      IFS=',' read -r -a items <<< "$s"
      for it in "${items[@]}"; do SHOW_LIST+=("$(echo "$it" | tr '[:upper:]' '[:lower:]' | xargs)"); done
      ;;
    --show-all) SHOW_ALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

# default to manifest only if nothing requested
if [[ ${#SHOW_LIST[@]} -eq 0 && $SHOW_ALL -eq 0 ]]; then
  SHOW_LIST=("manifest")
fi

ALL_CATEGORIES=("manifest" "jobs" "scripts" "yaml" "artefacts")
if [[ $SHOW_ALL -eq 1 ]]; then
  SHOW_LIST=("${ALL_CATEGORIES[@]}")
fi

has_show() {
  local want="$1"
  if [[ $SHOW_ALL -eq 1 ]]; then return 0; fi
  for s in "${SHOW_LIST[@]}"; do
    if [[ "$s" == "$want" ]]; then return 0; fi
  done
  return 1
}

# detect whether user supplied --results-root (long or with =)
RESULTS_SPECIFIED=false
for a in "${ARGS[@]:-}"; do
  case "$a" in
    --results-root|--results-root=*) RESULTS_SPECIFIED=true; break ;;
  esac
done

if [[ $RESULTS_SPECIFIED == false ]]; then
  mkdir -p "$TMP_PARENT"
  TMPDIR=$(mktemp -d "$TMP_PARENT/valska-bayeseor-manifests-XXXX")
  trap '[[ ${KEEP:-0} -eq 0 ]] && rm -rf "$TMPDIR"' EXIT
  CLI_ARGS=("${ARGS[@]}" --results-root "$TMPDIR")
  SEARCH_ROOT="$TMPDIR"
else
  CLI_ARGS=("${ARGS[@]}")
  # extract the value of --results-root
  SEARCH_ROOT=""
  NEXT=0
  for a in "${ARGS[@]}"; do
    case "$a" in
      --results-root=*) SEARCH_ROOT="${a#*=}"; break ;;
      --results-root) NEXT=1; continue ;;
    esac
    if [[ "${NEXT:-0}" -eq 1 ]]; then SEARCH_ROOT="$a"; NEXT=0; fi
  done
  if [[ -z "$SEARCH_ROOT" ]]; then
    echo "Cannot determine --results-root value from args" >&2
    exit 1
  fi
fi

echo "Running: valska-bayeseor-prepare ${CLI_ARGS[*]}"
valska-bayeseor-prepare "${CLI_ARGS[@]}"

found=0
failures=0

# iterate manifest.json files
while IFS= read -r -d '' mf; do
  found=$((found+1))
  manifest_dir=$(dirname "$mf")
  echo
  echo "==== Manifest: $mf ===="

  # Always parse manifest (use jq if available, fall back to python)
  if command -v jq >/dev/null 2>&1; then
    manifest_tool=$(jq -r '.tool // ""' "$mf")
    manifest_json_raw=$(jq -c '.' "$mf")
  else
    manifest_tool=$(python - <<PY
import json,sys
m=json.load(open(r"$mf"))
print(m.get("tool",""))
PY
)
    manifest_json_raw=$(python - <<PY
import json,sys
m=json.load(open(r"$mf"))
print(json.dumps(m))
PY
)
  fi

  # pretty-print manifest if requested
  if has_show manifest; then
    if command -v jq >/dev/null 2>&1; then
      jq '.' "$mf" || true
    else
      python - <<PY || true
import json,sys
m=json.load(open(r"$mf"))
print(json.dumps(m, indent=2))
PY
    fi
  fi

  # check tool field
  if [[ "$manifest_tool" != "bayeseor" ]]; then
    echo "ERROR: manifest tool='$manifest_tool' (expected 'bayeseor')" >&2
    failures=$((failures+1))
  else
    echo "OK: manifest tool is 'bayeseor'"
  fi

  # print jobs.json
  if has_show jobs && [[ -f "$manifest_dir/jobs.json" ]]; then
    echo "---- jobs.json ----"
    if command -v jq >/dev/null 2>&1; then
      jq '.' "$manifest_dir/jobs.json" || true
    else
      python - <<PY || true
import json
print(json.dumps(json.load(open(r"$manifest_dir/jobs.json")), indent=2))
PY
    fi
  fi

  # print submit scripts (*.sbatch, submit*.sh)
  if has_show scripts; then
    shopt -s nullglob
    for s in "$manifest_dir"/*.sbatch "$manifest_dir"/submit*.sh; do
      [ -e "$s" ] || continue
      echo "---- $s ----"
      sed -n '1,200p' "$s"
    done
    shopt -u nullglob
  fi

  # print yaml files
  if has_show yaml; then
    shopt -s nullglob
    for y in "$manifest_dir"/*.yaml "$manifest_dir"/*.yml; do
      [ -e "$y" ] || continue
      echo "---- $y ----"
      if command -v yq >/dev/null 2>&1; then
        yq '.' "$y" || true
      else
        sed -n '1,200p' "$y"
      fi
    done
    shopt -u nullglob
  fi

  # print artefacts referenced in manifest (if requested)
  if has_show artefacts; then
    python - <<PY || true
import json,os
m=json.load(open(r"$mf"))
arts = m.get("artefacts", {})
if arts:
    print("---- artefacts (from manifest) ----")
    for k,v in (arts.items() if isinstance(arts, dict) else enumerate(arts)):
        if isinstance(k, int):
            name = str(k)
            path = v
        else:
            name = k
            path = v
        print(f"{name}: {path}")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for i,l in enumerate(fh):
                        if i>=20:
                            print("  ... (truncated)")
                            break
                        print("  " + l.rstrip())
            except Exception:
                print("  (binary or unreadable)")
        else:
            print("  (does not exist)")
else:
    print("No artefacts listed in manifest")
PY
  fi

done < <(find "$SEARCH_ROOT" -type f -name manifest.json -print0)

if [[ "$found" -eq 0 ]]; then
  echo "No manifest.json files found under: $SEARCH_ROOT" >&2
  exit 2
fi

if [[ "$failures" -ne 0 ]]; then
  echo "$failures manifest(s) failed checks" >&2
  exit 3
fi

echo
echo "Checked $found manifest(s) — all OK"
if [[ "${KEEP:-0}" -eq 1 && -n "${TMPDIR:-}" ]]; then
  echo "Temporary results-root kept at: $TMPDIR"
  trap - EXIT
fi

exit 0
