#!/usr/bin/env bash
set -euxo pipefail
if [ -d /root/venv/bin ]; then
  export PATH=/root/venv/bin:$PATH
fi
PY_BIN=python3
if [ -x /root/venv/bin/python ]; then
  PY_BIN=/root/venv/bin/python
elif [ -x /opt/conda/bin/python ]; then
  PY_BIN=/opt/conda/bin/python
elif command -v python >/dev/null 2>&1; then
  PY_BIN=python
fi
if [ -d /opt/conda/bin ]; then
  export PATH=/opt/conda/bin:$PATH
fi
PY_SITE=$($PY_BIN - <<'PY'
import site
for p in site.getsitepackages():
    if p.endswith("site-packages"):
        print(p)
        break
PY
)
for d in nvidia/cuda_runtime/lib nvidia/cublas/lib nvidia/cudnn/lib nvidia/cusparse/lib nvidia/cusolver/lib nvidia/nccl/lib; do
  if [ -d "${PY_SITE}/${d}" ]; then
    export LD_LIBRARY_PATH="${PY_SITE}/${d}:${LD_LIBRARY_PATH:-}"
  fi
done
cd /workspace/slime
$PY_BIN - <<'PY'
from pathlib import Path
import pandas as pd
from huggingface_hub import snapshot_download

root = Path('/root/lium_min')
root.mkdir(parents=True, exist_ok=True)
model_dir = Path('/root/models/Qwen3-0.6B')
if not model_dir.exists():
    snapshot_download(repo_id='Qwen/Qwen3-0.6B', local_dir=str(model_dir))
rows = [
    {'messages': [{'role': 'user', 'content': 'Answer with one word: sky color'}], 'label': 'blue'},
    {'messages': [{'role': 'user', 'content': 'Answer with one word: grass color'}], 'label': 'green'},
]
pd.DataFrame(rows).to_parquet('/root/lium_min/tiny_rl.parquet', index=False)
PY
ray stop --force || true
#
# Ray's visible GPU count must be consistent with how we schedule RL.
# Non-colocated RL typically needs 2 GPUs (actor + rollout engine).
# If Ray is started with only 1 GPU, we must enable --colocate.
#
# Default: expose all visible GPUs to Ray (safe inside a dedicated pod).
# Override by setting LIUM_RAY_NUM_GPUS=1 (or any integer).
RAY_NUM_GPUS=1
GPU_COUNT=0
if command -v nvidia-smi >/dev/null 2>&1; then
  GPU_COUNT="$(nvidia-smi -L 2>/dev/null | wc -l | tr -d ' ')"
fi
if [ "${GPU_COUNT:-0}" -gt 0 ]; then
  RAY_NUM_GPUS="${GPU_COUNT}"
fi
if [ -n "${LIUM_RAY_NUM_GPUS:-}" ]; then
  RAY_NUM_GPUS="${LIUM_RAY_NUM_GPUS}"
fi
ray start --head --node-ip-address 127.0.0.1 --num-gpus "${RAY_NUM_GPUS}" --disable-usage-stats

# Minimal RL can require 2 GPUs (actor + rollout engine) unless colocated.
# Auto-enable colocate when Ray only exposes 1 GPU.
COLOCATE_ARGS=()
OFFLOAD_ARGS=()
if [ "${RAY_NUM_GPUS:-1}" -le 1 ]; then
  COLOCATE_ARGS+=(--colocate)
  # Colocate mode currently defaults to offload; for a minimal smoke test we
  # prefer keeping the rollout engine on GPU to avoid extra moving parts.
  OFFLOAD_ARGS+=(--no-offload-train --no-offload-rollout)
fi
$PY_BIN train.py \
  --hf-checkpoint /root/models/Qwen3-0.6B \
  --attn-implementation sdpa \
  --prompt-data /root/lium_min/tiny_rl.parquet \
  --input-key messages \
  --label-key label \
  --apply-chat-template \
  --rollout-shuffle \
  --rm-type f1 \
  --num-epoch 1 \
  --num-rollout 2 \
  --rollout-batch-size 1 \
  --n-samples-per-prompt 1 \
  --rollout-max-response-len 16 \
  --rollout-temperature 0.7 \
  --global-batch-size 1 \
  --advantage-estimator grpo \
  --kl-loss-coef 0.0 \
  --entropy-coef 0.0 \
  --eps-clip 0.2 \
  --eps-clip-high 0.28 \
  --optimizer adam \
  --lr 1e-6 \
  --lr-decay-style constant \
  --weight-decay 0.1 \
  --adam-beta1 0.9 \
  --adam-beta2 0.98 \
  --rollout-num-gpus-per-engine 1 \
  --num-gpus-per-node 1 \
  --sglang-disable-cuda-graph \
  --sglang-mem-fraction-static 0.3 \
  --actor-num-nodes 1 \
  --actor-num-gpus-per-node 1 \
  --rollout-num-gpus 1 \
  --train-backend fsdp \
  --no-save-optim \
  "${COLOCATE_ARGS[@]}" \
  "${OFFLOAD_ARGS[@]}" \
  --save /root/lium_min/rl_ckpt \
  --save-interval 2
