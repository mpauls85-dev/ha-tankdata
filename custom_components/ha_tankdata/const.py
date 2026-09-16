"""Integration constants."""

DOMAIN = "ha_tankdata"
VERSION = "0.4.0"
ACTIONS = {
    "record_observation": "observation",
    "record_refill": "refill",
    "record_withdrawal": "withdrawal",
    "apply_correction": "correction",
    "reset_calibration": "reset",
    "recalculate": None,
}
