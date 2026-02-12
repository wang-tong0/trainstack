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
${PY_BIN} - <<'PY'
from pathlib import Path
import pandas as pd
from huggingface_hub import snapshot_download

root = Path("/root/lium_min")
root.mkdir(parents=True, exist_ok=True)

model_dir = Path("/root/models/Qwen3-0.6B")
if not model_dir.exists():
    snapshot_download(repo_id="Qwen/Qwen3-0.6B", local_dir=str(model_dir))

rows = [
    {
        "messages": [
            {"role": "user", "content": "Answer with one word: sky color"},
            {"role": "assistant", "content": "blue"},
        ]
    },
    {
        "messages": [
            {"role": "user", "content": "Answer with one word: grass color"},
            {"role": "assistant", "content": "green"},
        ]
    },
]
pd.DataFrame(rows).to_parquet("/root/lium_min/tiny_sft.parquet", index=False)
PY
ray stop --force || true
ray start --head --node-ip-address 127.0.0.1 --num-gpus 1 --disable-usage-stats
$PY_BIN train.py \
  --hf-checkpoint /root/models/Qwen3-0.6B \
  --attn-implementation sdpa \
  --prompt-data /root/lium_min/tiny_sft.parquet \
  --input-key messages \
  --rollout-function-path slime.rollout.sft_rollout.generate_rollout \
  --rollout-shuffle \
  --num-epoch 1 \
  --num-rollout 2 \
  --rollout-batch-size 1 \
  --global-batch-size 1 \
  --loss-type sft_loss \
  --calculate-per-token-loss \
  --debug-train-only \
  --actor-num-nodes 1 \
  --actor-num-gpus-per-node 1 \
  --train-backend fsdp \
  --no-save-optim \
  --save /root/lium_min/sft_ckpt \
  --save-interval 1
