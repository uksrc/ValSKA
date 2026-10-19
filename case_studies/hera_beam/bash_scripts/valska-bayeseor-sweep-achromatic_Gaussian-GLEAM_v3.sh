#!/bin/bash
# Prepare or submit the v3 BayesEoR sweep for achromatic_Gaussian + GLEAM.

set -euo pipefail

BEAM="achromatic_Gaussian"
SKY="GLEAM"
DATA="gleam-158.30-167.10-MHz-nf-38-pld-mean-2.82-std-0.19-fov-19.4deg-circ-field-1_quentin.uvh5"
DATA_ROOT_KEY="gaussian"
TEMPLATE="validation_achromatic_Gaussian.yaml"
RUN_ID="sweep_v3"
PERTURB_PARAMETER="fwhm_deg"
FWHM_FRACS=(-0.2 -0.1 -0.05 -0.02 -0.01 0.0 0.01 0.02 0.05 0.1 0.2)

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/valska-bayeseor-sweep-v3-common.sh"
