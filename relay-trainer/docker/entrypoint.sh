#!/usr/bin/env bash
set -euo pipefail

if [[ ! -d "/mnt" ]]; then
  echo "/mnt missing; Lium volume is required" >&2
  exit 2
fi
if [[ ! -w "/mnt" ]]; then
  echo "/mnt not writable; check Lium volume mount permissions" >&2
  exit 2
fi

export PYTHONUNBUFFERED=1

exec python -m relay.worker.relay_entry --config "${RELAY_RUN_CONFIG:-configs/run.yaml}"
