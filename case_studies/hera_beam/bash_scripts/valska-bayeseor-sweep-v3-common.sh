#!/bin/bash
# Shared implementation for v3 BayesEoR sweep wrappers.
#
# Source this file from a campaign-specific wrapper after setting:
#   BEAM, SKY, DATA, DATA_ROOT_KEY, TEMPLATE, RUN_ID, PERTURB_PARAMETER
# and either FWHM_FRACS or ANTENNA_DIAMETER_FRACS.

set -euo pipefail

: "${BEAM:?BEAM must be set by the wrapper}"
: "${SKY:?SKY must be set by the wrapper}"
: "${DATA:?DATA must be set by the wrapper}"
: "${DATA_ROOT_KEY:?DATA_ROOT_KEY must be set by the wrapper}"
: "${TEMPLATE:?TEMPLATE must be set by the wrapper}"
: "${RUN_ID:?RUN_ID must be set by the wrapper}"
: "${PERTURB_PARAMETER:?PERTURB_PARAMETER must be set by the wrapper}"

COMMON_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$COMMON_SCRIPT_DIR/../../.." && pwd)"

RESULTS_ROOT="${RESULTS_ROOT:-$REPO_ROOT/validation_results/UKSRC/v2}"
VALSKA_BAYESEOR_SWEEP_CMD="${VALSKA_BAYESEOR_SWEEP_CMD:-valska-bayeseor-sweep}"
VALSKA_BAYESEOR_REPORT_CMD="${VALSKA_BAYESEOR_REPORT_CMD:-valska-bayeseor-report}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-$REPO_ROOT/temp/tmp/matplotlib}"
mkdir -p "$MPLCONFIGDIR"
SUBMIT_MODE="none"
SUBMIT_MODE_KIND="per-point"
ARRAY_MAX_CPU=""
ARRAY_MAX_GPU=""
USE_DRY_RUN="false"
SUBMIT_DRY_RUN="false"
RUN_REPORT="false"
REPORT_NO_PLOTS="false"
REPORT_ASSETS_DIR=""
FORCE="false"
RESUBMIT="false"

usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  --submit none|cpu|gpu|all     Prepare only or submit CPU/GPU/all jobs (default: none).
    --submit-mode per-point|array Submission strategy for sweep jobs (default: per-point).
    --array-max-cpu N             Max concurrent CPU array tasks when --submit-mode array.
    --array-max-gpu N             Max concurrent GPU array tasks when --submit-mode array.
  --run-id ID                   Override the sweep run ID (default: $RUN_ID).
  --results-root DIR            Override results root (default: $RESULTS_ROOT).
  --dry-run                     Show the sweep plan without creating files or jobs.
  --submit-dry-run              Prepare files and show sbatch commands without submitting jobs.
  --report                      Generate the standard report after the sweep command finishes.
  --report-no-plots             Generate report tables only.
  --report-assets-dir DIR       Copy report artefacts into DIR and write artefact_manifest.json.
  --force                       Pass --force to valska-bayeseor-sweep.
  --resubmit                    Pass --resubmit to valska-bayeseor-sweep.
  -h, --help                    Show this help.

Examples:
  conda activate valska
  $0 --dry-run
  $0 --submit none
  $0 --submit all
  $0 --submit all --submit-dry-run
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --submit)
            SUBMIT_MODE="${2:-}"
            shift 2
            ;;
        --run-id)
            RUN_ID="${2:-}"
            shift 2
            ;;
        --submit-mode)
            SUBMIT_MODE_KIND="${2:-}"
            shift 2
            ;;
        --array-max-cpu)
            ARRAY_MAX_CPU="${2:-}"
            shift 2
            ;;
        --array-max-gpu)
            ARRAY_MAX_GPU="${2:-}"
            shift 2
            ;;
        --results-root)
            RESULTS_ROOT="${2:-}"
            shift 2
            ;;
        --dry-run)
            USE_DRY_RUN="true"
            shift
            ;;
        --submit-dry-run)
            SUBMIT_DRY_RUN="true"
            shift
            ;;
        --report)
            RUN_REPORT="true"
            shift
            ;;
        --report-no-plots)
            RUN_REPORT="true"
            REPORT_NO_PLOTS="true"
            shift
            ;;
        --report-assets-dir)
            RUN_REPORT="true"
            REPORT_ASSETS_DIR="${2:-}"
            shift 2
            ;;
        --force)
            FORCE="true"
            shift
            ;;
        --resubmit)
            RESUBMIT="true"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Error: Unknown argument '$1'" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ ! "$SUBMIT_MODE" =~ ^(none|cpu|gpu|all)$ ]]; then
    echo "Error: Invalid submit mode '$SUBMIT_MODE'. Use: none, cpu, gpu, or all." >&2
    exit 1
fi

if [[ ! "$SUBMIT_MODE_KIND" =~ ^(per-point|array)$ ]]; then
    echo "Error: Invalid --submit-mode '$SUBMIT_MODE_KIND'. Use: per-point or array." >&2
    exit 1
fi

if [[ -z "$RUN_ID" ]]; then
    echo "Error: --run-id must not be empty." >&2
    exit 1
fi

if [[ -z "$RESULTS_ROOT" ]]; then
    echo "Error: --results-root must not be empty." >&2
    exit 1
fi

echo "Starting ValSKA BayesEoR v3 sweep..."
echo "  Beam:              $BEAM"
echo "  Sky:               $SKY"
echo "  Results root:      $RESULTS_ROOT"
echo "  Data root key:     $DATA_ROOT_KEY"
echo "  Data:              $DATA"
echo "  Template:          $TEMPLATE"
echo "  Sweep command:     $VALSKA_BAYESEOR_SWEEP_CMD"
echo "  Report command:    $VALSKA_BAYESEOR_REPORT_CMD"
echo "  Run ID:            $RUN_ID"
echo "  Perturb parameter: $PERTURB_PARAMETER"
if [[ "$PERTURB_PARAMETER" == "fwhm_deg" ]]; then
    echo "  FWHM fractions:    ${FWHM_FRACS[*]}"
else
    echo "  Diameter fractions:${ANTENNA_DIAMETER_FRACS[*]}"
fi
if [[ "${POL:-}" != "" ]]; then
    echo "  Polarisation:      $POL"
fi
echo "  Submit:            $SUBMIT_MODE"
echo "  Submit mode:       $SUBMIT_MODE_KIND"
if [[ "$SUBMIT_MODE_KIND" == "array" ]]; then
    echo "  Array max CPU:     ${ARRAY_MAX_CPU:-<none>}"
    echo "  Array max GPU:     ${ARRAY_MAX_GPU:-<none>}"
fi
echo "  Dry run:           $USE_DRY_RUN"
echo "  Submit dry run:    $SUBMIT_DRY_RUN"
echo "  Run report:        $RUN_REPORT"
echo ""

read -r -a sweep_exe <<< "$VALSKA_BAYESEOR_SWEEP_CMD"
cmd=(
    "${sweep_exe[@]}"
    --beam "$BEAM"
    --sky "$SKY"
    --results-root "$RESULTS_ROOT"
    --data-root-key "$DATA_ROOT_KEY"
    --data "$DATA"
    --template "$TEMPLATE"
    --run-id "$RUN_ID"
    --perturb-parameter "$PERTURB_PARAMETER"
    --submit "$SUBMIT_MODE"
    --submit-mode "$SUBMIT_MODE_KIND"
)

if [[ "${POL:-}" != "" ]]; then
    cmd+=(--override "pol=$POL")
fi

if [[ "$PERTURB_PARAMETER" == "fwhm_deg" ]]; then
    cmd+=(--fwhm-fracs "${FWHM_FRACS[@]}")
elif [[ "$PERTURB_PARAMETER" == "antenna_diameter" ]]; then
    cmd+=(--antenna-diameter-fracs "${ANTENNA_DIAMETER_FRACS[@]}")
else
    echo "Error: Unsupported perturb parameter '$PERTURB_PARAMETER'." >&2
    exit 1
fi

if [[ "$USE_DRY_RUN" == "true" ]]; then
    cmd+=(--dry-run)
fi

if [[ "$SUBMIT_DRY_RUN" == "true" ]]; then
    cmd+=(--submit-dry-run)
fi

if [[ "$FORCE" == "true" ]]; then
    cmd+=(--force)
fi

if [[ "$RESUBMIT" == "true" ]]; then
    cmd+=(--resubmit)
fi

if [[ "$ARRAY_MAX_CPU" != "" ]]; then
    cmd+=(--array-max-cpu "$ARRAY_MAX_CPU")
fi

if [[ "$ARRAY_MAX_GPU" != "" ]]; then
    cmd+=(--array-max-gpu "$ARRAY_MAX_GPU")
fi

"${cmd[@]}"

if [[ "$RUN_REPORT" == "true" ]]; then
    if [[ "$USE_DRY_RUN" == "true" ]]; then
        echo ""
        echo "Skipping report generation because --dry-run was set."
        exit 0
    fi

    SWEEP_DIR="$RESULTS_ROOT/bayeseor/$BEAM/$SKY/_sweeps/$RUN_ID"
    echo ""
    echo "Generating sweep report for: $SWEEP_DIR"

    read -r -a report_exe <<< "$VALSKA_BAYESEOR_REPORT_CMD"
    report_cmd=(
        "${report_exe[@]}"
        "$SWEEP_DIR"
        --include-plot-analysis-results
        --include-complete-analysis-table
    )

    if [[ "$REPORT_NO_PLOTS" == "true" ]]; then
        report_cmd+=(--no-plots)
    fi

    if [[ "$REPORT_ASSETS_DIR" != "" ]]; then
        report_cmd+=(--export-report-assets "$REPORT_ASSETS_DIR")
    fi

    "${report_cmd[@]}"
fi
