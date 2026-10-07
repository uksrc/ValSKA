#!/usr/bin/env bash
# Quick helper: run valska-bayeseor-prepare into a temp results-root, print any manifest.json found,
# and check that manifest.tool == "bayeseor".
# Usage: ./bash_scripts/check_bayeseor_manifests.sh [--keep] <valska-bayeseor-prepare args...>
#
# Exact usage example:
# ./bash_scripts/check_bayeseor_manifests.sh --keep \
#   --beam chromatic_Gaussian \
#   --sky GLEAM \
#   --data-root-key gaussian \
#   --data "gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5" \
#   --template validation_chromatic_Gaussian.yaml \
#   --run-id sweep

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
TMP_PARENT="${VALSKA_TMPDIR:-$PROJECT_ROOT/temp/tmp}"

KEEP=0
ARGS=()
for a in "$@"; do
  if [ "$a" = "--keep" ]; then KEEP=1; continue; fi
  ARGS+=("$a")
done

# Detect whether user supplied --results-root
RESULTS_SPECIFIED=false
for a in "${ARGS[@]:-}"; do
  case "$a" in
    --results-root|--results-root=*) RESULTS_SPECIFIED=true; break ;;
  esac
done

if [ "$RESULTS_SPECIFIED" = false ]; then
  mkdir -p "$TMP_PARENT"
  TMPDIR=$(mktemp -d "$TMP_PARENT/valska-bayeseor-manifests-XXXX")
  trap 'if [ "${KEEP:-0}" -eq 0 ]; then rm -rf "$TMPDIR"; fi' EXIT
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
    if [ "${NEXT:-0}" -eq 1 ]; then SEARCH_ROOT="$a"; NEXT=0; fi
  done
  if [ -z "$SEARCH_ROOT" ]; then
    echo "Cannot determine --results-root value from args" >&2
    exit 1
  fi
fi

echo "Running: valska-bayeseor-prepare ${CLI_ARGS[*]}"
valska-bayeseor-prepare "${CLI_ARGS[@]}"

found=0
failures=0

while IFS= read -r -d '' mf; do
  found=$((found+1))
  echo
  echo "==== Manifest: $mf ===="
  if command -v jq >/dev/null 2>&1; then
    jq '.' "$mf" || true
    tool=$(jq -r '.tool // ""' "$mf")
  else
    python - <<PY
import json,sys
m=json.load(open("$mf"))
print(json.dumps(m, indent=2))
print()
print("TOOL:", m.get("tool"))
PY
    tool=$(python - <<PY
import json
print(json.load(open("$mf")).get("tool",""))
PY
)
  fi

  if [ "$tool" != "bayeseor" ]; then
    echo "ERROR: manifest tool='$tool' (expected 'bayeseor')" >&2
    failures=$((failures+1))
  else
    echo "OK: manifest tool is 'bayeseor'"
  fi
done < <(find "$SEARCH_ROOT" -type f -name manifest.json -print0)

if [ "$found" -eq 0 ]; then
  echo "No manifest.json files found under: $SEARCH_ROOT" >&2
  exit 2
fi

if [ "$failures" -ne 0 ]; then
  echo "$failures manifest(s) failed checks" >&2
  exit 3
fi

echo
echo "Checked $found manifest(s) — all OK"
if [ "${KEEP:-0}" -eq 1 ] && [ -n "${TMPDIR:-}" ]; then
  echo "Temporary results-root kept at: $TMPDIR"
  trap - EXIT
fi

exit 0
