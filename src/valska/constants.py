"""Shared scientific defaults for ValSKA analyses."""

# Default injected 21-cm signal and thermal-noise power levels.
DEFAULT_EOR_POWER_MK2_MPC3 = 214777.66068216303
DEFAULT_NOISE_TO_EOR_POWER_RATIO = 0.5
DEFAULT_NOISE_POWER_MK2_MPC3 = (
    DEFAULT_EOR_POWER_MK2_MPC3 * DEFAULT_NOISE_TO_EOR_POWER_RATIO
)
