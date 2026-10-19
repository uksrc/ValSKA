#!/bin/bash
#
# Submit a BayesEoR FWHM perturbation sweep for achromatic_Gaussian beam + GLEAM sky.
#
# Usage:
#   ./valska-bayeseor-sweep-achromatic_Gaussian-GLEAM_v2.sh [none|cpu|all]
#
# Examples:
#   ./valska-bayeseor-sweep-achromatic_Gaussian-GLEAM_v2.sh       # Submits all (default)
#   ./valska-bayeseor-sweep-achromatic_Gaussian-GLEAM_v2.sh all   # Submits all (explicit)
#   ./valska-bayeseor-sweep-achromatic_Gaussian-GLEAM_v2.sh none  # Prepare only, no submission

set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration (edit these as needed)
# -----------------------------------------------------------------------------
BEAM="achromatic_Gaussian"
SKY="GLEAM"
# DATA="gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5"
DATA="gleam-158.30-167.10-MHz-nf-38-pld-mean-2.82-std-0.19-fov-19.4deg-circ-field-1_quentin.uvh5"
DATA_ROOT_KEY="gaussian"
RUN_ID="sweep"
TEMPLATE="validation_achromatic_Gaussian.yaml"


# gleam-158.30-167.10-MHz-nf-38-pld-mean-2.82-std-0.19-fov-12.9deg-circ-field-1_quentin.uvh5
# gleam-158.30-167.10-MHz-nf-38-pld-mean-2.82-std-0.19-fov-19.4deg-circ-field-1_quentin.uvh5
# gleam-field-1-pld-mean-2.82-std-0.19-nf-38-nt-34-dt-11s-fov-19.4deg_quentin.uvh5
# gleam-pld-mean-2.82-std-0.19-field-1-hex37-14.6m-nt-34-dt-11s-fov-19.4deg_jacob.uvh5
# gsm-nside256-158.3-167.1MHz-nf-38-fov-12.9deg-circ-field-1_quentin.uvh5
# gsm-nside256-158.3-167.1MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5
# gsm-nside256-158.3-167.1MHz-nf-38-fov-19.4-field-1_quentin.uvh5
# gsm-nside256-field-1-hex37-14.6m-nt-34-dt-11s-fov-19.4deg_jacob.uvh5
# gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-12.9deg-circ-field-1_quentin.uvh5
# gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5
# gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg_quentin.uvh5




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
