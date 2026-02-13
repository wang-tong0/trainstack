#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

LIVEWEB_ROOT="${LIVEWEB_ARENA_ROOT:-/home/ubuntu/liveweb-arena}"
LIVEWEB_PY="${LIVEWEB_ROOT}/.venv/bin/python"
if [[ ! -x "${LIVEWEB_PY}" ]]; then
  echo "missing liveweb python: ${LIVEWEB_PY}" >&2
  exit 2
fi

export PYTHONPATH="${REPO_ROOT}/slime:${REPO_ROOT}:${LIVEWEB_ROOT}:${PYTHONPATH:-}"
export TRAINSTACK_HTTP_ENV_URL="http://127.0.0.1:18082"
export TRAINSTACK_LLM_URL="http://127.0.0.1:18081/generate"
export LIVEWEB_ARENA_ROOT="${LIVEWEB_ROOT}"
export TRAINSTACK_SMOKE_HF_CHECKPOINT="${TRAINSTACK_SMOKE_HF_CHECKPOINT:-gpt2}"

# Force mock LLM to emit a valid liveweb stop action JSON.
export TRAINSTACK_MOCK_LLM_TEXT='{"action":{"type":"stop","params":{"format":"json","final":{"answers":{"answer1":"test"}}}}}'

cleanup() {
  if [[ -n "${ENV_PID:-}" ]]; then
    kill "${ENV_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${LLM_PID:-}" ]]; then
    kill "${LLM_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

"${LIVEWEB_PY}" -m pip install -q fastapi uvicorn >/dev/null

"${LIVEWEB_PY}" -m trainstack_plugins.http_env.liveweb_server >/tmp/trainstack_liveweb_env.log 2>&1 &
ENV_PID=$!
"${LIVEWEB_PY}" -m trainstack_plugins.http_env.mock_llm_server >/tmp/trainstack_liveweb_mock_llm.log 2>&1 &
LLM_PID=$!
sleep 3

"${LIVEWEB_PY}" - <<'PY'
import asyncio
import os
from argparse import Namespace
from dataclasses import dataclass, field
from enum import Enum

from slime.utils.http_utils import init_http_client
from trainstack_plugins.http_env.adapter import generate


@dataclass
class FakeSample:
    class Status(Enum):
        PENDING = "pending"
        COMPLETED = "completed"
        TRUNCATED = "truncated"
        ABORTED = "aborted"
        FAILED = "failed"

    prompt: str = ""
    label: dict | str | None = None
    metadata: dict = field(default_factory=dict)
    reward: float | None = None
    response: str = ""
    response_length: int = 0
    tokens: list[int] = field(default_factory=list)
    loss_mask: list[int] | None = None
    rollout_log_probs: list[float] | None = None
    status: Status = Status.PENDING


async def main():
    args = Namespace(
        partial_rollout=False,
        hf_checkpoint=os.environ["TRAINSTACK_SMOKE_HF_CHECKPOINT"],
        sglang_router_ip="127.0.0.1",
        sglang_router_port=30000,
        rollout_max_response_len=256,
        rollout_num_gpus=1,
        rollout_num_gpus_per_engine=1,
        sglang_server_concurrency=1,
        use_distributed_post=False,
        num_gpus_per_node=1,
    )
    init_http_client(args)
    sample = FakeSample(
        prompt="Solve the task and stop.",
        label={"task_id": 100001},
        metadata={"seed": 42},
    )
    out = await generate(
        args,
        sample,
        {"max_new_tokens": 128, "temperature": 0.0, "top_p": 1.0, "top_k": -1},
    )
    print("status:", out.status.value)
    print("reward:", out.reward)
    print("response_length:", out.response_length)
    print("response_head:", out.response[:200].replace("\n", " "))
    assert out.status.value in {"completed", "truncated"}
    assert out.response_length > 0


asyncio.run(main())
PY

echo "liveweb smoke test passed"

