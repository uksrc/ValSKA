#!/bin/bash
# Prepare or submit the v3 BayesEoR sweep for airy_diam14m + GSM_plus_GLEAM.

set -euo pipefail

BEAM="airy_diam14m"
SKY="GSM_plus_GLEAM"
DATA="gsm_plus_gleam-158.30-167.10-MHz-nf-38-fov-19.4deg-circ-field-1-airy_quentin.uvh5"
DATA_ROOT_KEY="airy_diam14m"
TEMPLATE="validation_airy_diam14m.yaml"
RUN_ID="sweep_airy_v3"
PERTURB_PARAMETER="antenna_diameter"
POL="xx"
ANTENNA_DIAMETER_FRACS=(-0.2 -0.1 -0.05 -0.02 -0.01 0.0 0.01 0.02 0.05 0.1 0.2)

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/valska-bayeseor-sweep-v3-common.sh"
