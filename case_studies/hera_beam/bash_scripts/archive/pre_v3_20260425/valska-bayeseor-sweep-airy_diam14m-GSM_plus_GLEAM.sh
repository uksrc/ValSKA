#!/bin/bash
#
# Run a BayesEoR sweep for an airy (14 m diameter) beam configuration.
# Default behaviour is prepare-only (no submission) across the configured
# antenna_diameter perturbation list.
#
# Usage:
#   ./valska-bayeseor-sweep-airy_diam14m-GSM_plus_GLEAM.sh [--submit none|cpu|gpu|all] [--run-id ID] [--dry-run] [--report] [--report-no-plots]
#
# Examples:
#   ./valska-bayeseor-sweep-airy_diam14m-GSM_plus_GLEAM.sh --dry-run
#   ./valska-bayeseor-sweep-airy_diam14m-GSM_plus_GLEAM.sh --submit none
#   ./valska-bayeseor-sweep-airy_diam14m-GSM_plus_GLEAM.sh --submit cpu
#   ./valska-bayeseor-sweep-airy_diam14m-GSM_plus_GLEAM.sh --submit all
#   ./valska-bayeseor-sweep-airy_diam14m-GSM_plus_GLEAM.sh --submit all --report

set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration (edit these as needed)
# -----------------------------------------------------------------------------
BEAM="airy_diam14m"
SKY="GSM_plus_GLEAM"
DATA="gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1-airy_quentin.uvh5"
DATA_ROOT_KEY="airy_diam14m"
TEMPLATE="validation_airy_diam14m.yaml"
RUN_ID="sweep_airy_init"
POL="xx"

# Initial airy check-point: single unperturbed run.
# ANTENNA_DIAMETER_FRACS="0.0"
# Default airy sweep fractions.
ANTENNA_DIAMETER_FRACS="-0.2 -0.1 -0.05 -0.02 -0.01 0.0 0.01 0.02 0.05 0.1 0.2"

# Defaults (can be overridden via CLI flags)
SUBMIT_MODE="none"
USE_DRY_RUN="false"
RUN_REPORT="false"
REPORT_NO_PLOTS="false"

# -----------------------------------------------------------------------------
# Arg parsing
# -----------------------------------------------------------------------------
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
        --dry-run)
            USE_DRY_RUN="true"
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
        *)
            echo "Error: Unknown argument '$1'" >&2
            echo "Usage: $0 [--submit none|cpu|gpu|all] [--run-id ID] [--dry-run] [--report] [--report-no-plots]" >&2
            exit 1
            ;;
    esac
done

if [[ ! "$SUBMIT_MODE" =~ ^(none|cpu|gpu|all)$ ]]; then
    echo "Error: Invalid submit mode '$SUBMIT_MODE'. Use: none, cpu, gpu, or all." >&2
    exit 1
fi

if [[ -z "$RUN_ID" ]]; then
    echo "Error: --run-id must not be empty." >&2
    exit 1
fi

# -----------------------------------------------------------------------------
# Run sweep
# -----------------------------------------------------------------------------
echo "Starting ValSKA BayesEoR airy sweep..."
echo "  Beam:                $BEAM"
echo "  Sky:                 $SKY"
echo "  Data root key:       $DATA_ROOT_KEY"
echo "  Data:                $DATA"
echo "  Template:            $TEMPLATE"
echo "  Polarization:        $POL"
echo "  Perturb parameter:   antenna_diameter"
echo "  antenna_diameter_fracs: $ANTENNA_DIAMETER_FRACS"
echo "  Run ID:              $RUN_ID"
echo "  Submit:              $SUBMIT_MODE"
echo "  Dry run:             $USE_DRY_RUN"
echo "  Run report:          $RUN_REPORT"
echo "  Report no plots:     $REPORT_NO_PLOTS"
echo ""

cmd=(
    valska-bayeseor-sweep
    --beam "$BEAM"
    --sky "$SKY"
    --data-root-key "$DATA_ROOT_KEY"
    --data "$DATA"
    --template "$TEMPLATE"
    --run-id "$RUN_ID"
    --override "pol=$POL"
    --perturb-parameter antenna_diameter
    --antenna-diameter-fracs $ANTENNA_DIAMETER_FRACS
    --submit "$SUBMIT_MODE"
)

if [[ "$USE_DRY_RUN" == "true" ]]; then
    cmd+=(--dry-run)
fi

"${cmd[@]}"

if [[ "$RUN_REPORT" == "true" ]]; then
    SWEEP_DIR="$(valska-bayeseor-sweep \
        --beam "$BEAM" \
        --sky "$SKY" \
        --run-id "$RUN_ID" \
        --template "$TEMPLATE" \
        --data-root-key "$DATA_ROOT_KEY" \
        --data "$DATA" \
        --override "pol=$POL" \
        --perturb-parameter antenna_diameter \
        --antenna-diameter-fracs $ANTENNA_DIAMETER_FRACS \
        --submit none \
        --dry-run --json | python -c 'import json,sys; print(json.load(sys.stdin)["sweep_dir"])')"

    echo ""
    echo "Generating sweep report for: $SWEEP_DIR"

    report_cmd=(
        valska-bayeseor-report
        "$SWEEP_DIR"
    )

    if [[ "$REPORT_NO_PLOTS" == "true" ]]; then
        report_cmd+=(--no-plots)
    fi

    "${report_cmd[@]}"
fi
