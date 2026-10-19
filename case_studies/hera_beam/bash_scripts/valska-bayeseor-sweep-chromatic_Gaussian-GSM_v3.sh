#!/bin/bash
# Prepare or submit the v3 BayesEoR sweep for chromatic_Gaussian + GSM.

set -euo pipefail

BEAM="chromatic_Gaussian"
SKY="GSM"
DATA="gsm-nside256-158.3-167.1MHz-nf-38-fov-19.4deg-circ-field-1_quentin.uvh5"
DATA_ROOT_KEY="gaussian"
TEMPLATE="validation_chromatic_Gaussian.yaml"
RUN_ID="sweep_v3"
PERTURB_PARAMETER="fwhm_deg"
FWHM_FRACS=(-0.2 -0.1 -0.05 -0.02 -0.01 0.0 0.01 0.02 0.05 0.1 0.2)

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/valska-bayeseor-sweep-v3-common.sh"
