#!/usr/bin/env bash
set -euo pipefail

RUN_ROOT="${RELAY_RUN_ROOT:?RELAY_RUN_ROOT is required}"
STAGING_ROOT="${RELAY_CKPT_STAGING_ROOT:?RELAY_CKPT_STAGING_ROOT is required}"
RESUME_FROM="${RELAY_RESUME_FROM:-}"

export RELAY_TRAIN_MODE="sft"
export RELAY_OUTPUT_DIR="${RUN_ROOT}/ckpt"
export RELAY_RESUME_FROM="${RESUME_FROM}"

if [[ -n "${SLIME_SFT_CMD:-}" ]]; then
  # Provide RELAY_OUTPUT_DIR / RELAY_RESUME_FROM to the command.
  eval "${SLIME_SFT_CMD}"
else
  python3 trainer_blackbox/mock_trainer.py --mode sft --max-steps "${MOCK_MAX_STEPS:-3}" --save-every 1 --staging-root "${STAGING_ROOT}"
fi
