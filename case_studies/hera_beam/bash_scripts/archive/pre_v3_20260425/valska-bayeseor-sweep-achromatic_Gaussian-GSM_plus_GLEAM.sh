#!/bin/bash
#
# Submit a BayesEoR FWHM perturbation sweep for achromatic_Gaussian beam + GSM_plus_GLEAM sky.
#
# Usage:
#   ./valska-bayeseor-sweep-achromatic_Gaussian-GSM_plus_GLEAM.sh [none|cpu|all]
#
# Examples:
#   ./valska-bayeseor-sweep-achromatic_Gaussian-GSM_plus_GLEAM.sh       # Submits all (default)
#   ./valska-bayeseor-sweep-achromatic_Gaussian-GSM_plus_GLEAM.sh all   # Submits all (explicit)
#   ./valska-bayeseor-sweep-achromatic_Gaussian-GSM_plus_GLEAM.sh none  # Prepare only, no submission

set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration (edit these as needed)
# -----------------------------------------------------------------------------
BEAM="achromatic_Gaussian"
SKY="GSM_plus_GLEAM"
DATA="gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5"
DATA_ROOT_KEY="gaussian"
RUN_ID="sweep"
TEMPLATE="validation_achromatic_Gaussian.yaml"

# FWHM perturbation fractions (negative = narrower, positive = wider)
FWHM_FRACS="-0.2 -0.1 -0.05 -0.02 -0.01 0.0 0.01 0.02 0.05 0.1 0.2"

# Default submission mode (can be overridden via CLI)
SUBMIT_MODE="${1:-all}"

# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------
if [[ ! "$SUBMIT_MODE" =~ ^(none|cpu|all)$ ]]; then
    echo "Error: Invalid submit mode '$SUBMIT_MODE'. Use: none, cpu, or all" >&2
    exit 1
fi

# -----------------------------------------------------------------------------
# Run sweep
# -----------------------------------------------------------------------------
echo "Starting ValSKA BayesEoR sweep..."
echo "  Beam:     $BEAM"
echo "  Sky:      $SKY"
echo "  Data root key: $DATA_ROOT_KEY"
echo "  Template: $TEMPLATE"
echo "  Run ID:   $RUN_ID"
echo "  Submit:   $SUBMIT_MODE"
echo ""

valska-bayeseor-sweep \
  --beam "$BEAM" \
  --sky "$SKY" \
  --data-root-key "$DATA_ROOT_KEY" \
  --data "$DATA" \
  --template "$TEMPLATE" \
  --run-id "$RUN_ID" \
  --fwhm-fracs $FWHM_FRACS \
  --submit "$SUBMIT_MODE"
