import os
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Trainstack HTTP Environment", version="0.1.0")


class StartRequest(BaseModel):
    task: dict[str, Any] = Field(default_factory=dict)


class StepRequest(BaseModel):
    session_id: str
    action: str


class CloseRequest(BaseModel):
    session_id: str


@dataclass
class Session:
    prompt: str
    label: Any
    metadata: dict[str, Any]
    step: int = 0
    done: bool = False
    reward: float | None = None


SESSIONS: dict[str, Session] = {}


def _extract_answer(label: Any) -> str:
    if label is None:
        return ""
    if isinstance(label, dict):
        return str(label.get("answer", label.get("ground_truth", ""))).strip()
    return str(label).strip()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/session/start")
async def start_session(req: StartRequest) -> dict[str, Any]:
    task = req.task or {}
    prompt = str(task.get("prompt", ""))
    label = task.get("label")
    metadata = task.get("metadata") or {}
    session_id = uuid.uuid4().hex
    SESSIONS[session_id] = Session(prompt=prompt, label=label, metadata=metadata)

    initial_observation = metadata.get(
        "initial_observation",
        "\nPlease provide the final answer in <answer>...</answer> format.\n",
    )
    return {
        "session_id": session_id,
        "observation": initial_observation,
        "done": False,
        "reward": None,
        "info": {"env": "simple_answer_env"},
    }


@app.post("/v1/session/step")
async def step_session(req: StepRequest) -> dict[str, Any]:
    sess = SESSIONS.get(req.session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    if sess.done:
        return {"observation": "", "done": True, "reward": sess.reward, "info": {"reason": "already_done"}}

    sess.step += 1
    expected = _extract_answer(sess.label)
    normalized_action = req.action.strip().lower()
    normalized_expected = expected.lower()

    is_correct = bool(normalized_expected) and normalized_expected in normalized_action
    reward = 1.0 if is_correct else 0.0
    sess.reward = reward
    sess.done = True

    observation = "\nEnvironment feedback: episode finished.\n"
    return {
        "observation": observation,
        "done": True,
        "reward": reward,
        "info": {
            "expected_answer": expected,
            "is_correct": is_correct,
            "steps": sess.step,
        },
    }


@app.post("/v1/session/close")
async def close_session(req: CloseRequest) -> dict[str, Any]:
    SESSIONS.pop(req.session_id, None)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("TRAINSTACK_HTTP_ENV_HOST", "0.0.0.0")
    port = int(os.getenv("TRAINSTACK_HTTP_ENV_PORT", "18080"))
    uvicorn.run(app, host=host, port=port)
