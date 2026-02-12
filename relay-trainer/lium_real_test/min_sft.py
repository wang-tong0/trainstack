import os
from pathlib import Path

import pandas as pd
import slime.utils.external_utils.command_utils as U
from huggingface_hub import snapshot_download

MODEL_NAME = "Qwen3-0.6B"
ROOT = Path("/root/lium_min")
DATA = ROOT / "tiny_sft.parquet"


def prepare():
    U.exec_command(f"mkdir -p {ROOT} /root/models")
    model_dir = Path(f"/root/models/{MODEL_NAME}")
    if not model_dir.exists():
        snapshot_download(repo_id=f"Qwen/{MODEL_NAME}", local_dir=str(model_dir))

    rows = [
        {"messages": [{"role": "user", "content": "2+2=?"}, {"role": "assistant", "content": "4"}]},
        {"messages": [{"role": "user", "content": "3+5=?"}, {"role": "assistant", "content": "8"}]},
    ]
    pd.DataFrame(rows).to_parquet(DATA, index=False)


def execute():
    train_args = (
        f"--hf-checkpoint /root/models/{MODEL_NAME} "
        f"--prompt-data {DATA} "
        "--input-key messages "
        "--rollout-function-path slime.rollout.sft_rollout.generate_rollout "
        "--rollout-shuffle "
        "--num-epoch 1 --num-rollout 2 "
        "--rollout-batch-size 1 "
        "--global-batch-size 1 "
        "--loss-type sft_loss "
        "--calculate-per-token-loss "
        "--disable-compute-advantages-and-returns "
        "--debug-train-only "
        "--actor-num-nodes 1 "
        "--actor-num-gpus-per-node 1 "
        "--train-backend fsdp "
        "--save /root/lium_min/sft_ckpt "
        "--save-interval 1 "    )

    U.execute_train(
        train_args=train_args,
        num_gpus_per_node=1,
        megatron_model_type=None,
        train_script="train.py",
    )


if __name__ == "__main__":
    for proxy_var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.pop(proxy_var, None)
    prepare()
    execute()
