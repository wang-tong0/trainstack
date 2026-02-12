import os
from pathlib import Path

import pandas as pd
import slime.utils.external_utils.command_utils as U
from huggingface_hub import snapshot_download

MODEL_NAME = "Qwen3-0.6B"
ROOT = Path("/root/lium_min")
DATA = ROOT / "tiny_rl.parquet"


def prepare():
    U.exec_command(f"mkdir -p {ROOT} /root/models")
    model_dir = Path(f"/root/models/{MODEL_NAME}")
    if not model_dir.exists():
        snapshot_download(repo_id=f"Qwen/{MODEL_NAME}", local_dir=str(model_dir))

    rows = [
        {"messages": [{"role": "user", "content": "Answer with one word: sky color"}], "label": "blue"},
        {"messages": [{"role": "user", "content": "Answer with one word: grass color"}], "label": "green"},
    ]
    pd.DataFrame(rows).to_parquet(DATA, index=False)


def execute():
    train_args = (
        f"--hf-checkpoint /root/models/{MODEL_NAME} "
        f"--prompt-data {DATA} "
        "--input-key messages "
        "--label-key label "
        "--apply-chat-template "
        "--rollout-shuffle "
        "--rm-type f1 "
        "--num-rollout 2 "
        "--rollout-batch-size 1 "
        "--n-samples-per-prompt 1 "
        "--rollout-max-response-len 16 "
        "--rollout-temperature 0.7 "
        "--global-batch-size 1 "
        "--advantage-estimator grpo "
        "--kl-loss-coef 0.0 "
        "--entropy-coef 0.0 "
        "--eps-clip 0.2 "
        "--eps-clip-high 0.28 "
        "--optimizer adam "
        "--lr 1e-6 "
        "--lr-decay-style constant "
        "--weight-decay 0.1 "
        "--adam-beta1 0.9 "
        "--adam-beta2 0.98 "
        "--rollout-num-gpus-per-engine 1 "
        "--sglang-mem-fraction-static 0.3 "
        "--actor-num-nodes 1 "
        "--actor-num-gpus-per-node 1 "
        "--rollout-num-gpus 1 "
        "--colocate "
        "--train-backend fsdp "
        "--save /root/lium_min/rl_ckpt "
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
