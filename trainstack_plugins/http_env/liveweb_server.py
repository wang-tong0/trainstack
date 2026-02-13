import os
import sys
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Trainstack LiveWeb HTTP Environment", version="0.1.0")


class StartRequest(BaseModel):
    task: dict[str, Any] = Field(default_factory=dict)


class StepRequest(BaseModel):
    session_id: str
    action: str


class CloseRequest(BaseModel):
    session_id: str


@dataclass
class Session:
    episode_id: str
    run_id: str
    done: bool = False


SESSIONS: dict[str, Session] = {}
ACTOR = None


def _setup_liveweb_import():
    root = os.getenv("LIVEWEB_ARENA_ROOT", "/home/ubuntu/liveweb-arena")
    if root not in sys.path:
        sys.path.insert(0, root)

    # Compatibility patch for current liveweb-arena branch:
    # env.py expects subtask.template, but SubTask currently exposes question.template.
    from liveweb_arena.plugins.base import SubTask

    if not hasattr(SubTask, "template"):
        SubTask.template = property(lambda self: getattr(self.question, "template", None))


def _task_id_from_label(label: Any) -> int | None:
    if label is None:
        return None
    if isinstance(label, dict) and "task_id" in label:
        return int(label["task_id"])
    if isinstance(label, int):
        return label
    if isinstance(label, str) and label.isdigit():
        return int(label)
    return None


def _seed_from_metadata(metadata: dict[str, Any]) -> int | None:
    seed = metadata.get("seed")
    if seed is None:
        return None
    return int(seed)


async def _get_actor():
    global ACTOR
    if ACTOR is None:
        _setup_liveweb_import()
        from env import Actor

        ACTOR = Actor()
    return ACTOR


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/session/start")
async def start_session(req: StartRequest) -> dict[str, Any]:
    task = req.task or {}
    metadata = task.get("metadata") or {}
    label = task.get("label")
    run_id = str(metadata.get("run_id", uuid.uuid4().hex))
    task_id = metadata.get("task_id")
    if task_id is None:
        task_id = _task_id_from_label(label)
    seed = _seed_from_metadata(metadata)

    actor = await _get_actor()
    try:
        reset = await actor.reset(task_id=task_id, seed=seed)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"liveweb reset failed: {exc}") from exc

    session_id = uuid.uuid4().hex
    SESSIONS[session_id] = Session(episode_id=reset.episode_id, run_id=run_id, done=bool(reset.done))
    return {
        "session_id": session_id,
        "observation": reset.observation,
        "done": bool(reset.done),
        "reward": float(reset.reward or 0.0),
        "info": reset.info or {},
    }


@app.post("/v1/session/step")
async def step_session(req: StepRequest) -> dict[str, Any]:
    session = SESSIONS.get(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.done:
        return {"observation": "", "done": True, "reward": 0.0, "info": {"reason": "already_done"}}

    actor = await _get_actor()
    try:
        out = await actor.step(action=req.action, episode_id=session.episode_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"liveweb step failed: {exc}") from exc

    session.done = bool(out.done)
    return {
        "observation": out.observation,
        "done": bool(out.done),
        "reward": float(out.reward or 0.0),
        "info": out.info or {},
    }


@app.post("/v1/session/close")
async def close_session(req: CloseRequest) -> dict[str, Any]:
    session = SESSIONS.pop(req.session_id, None)
    if session is not None:
        actor = await _get_actor()
        try:
            await actor.stop(episode_id=session.episode_id)
        except Exception:
            pass
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("TRAINSTACK_HTTP_ENV_HOST", "0.0.0.0")
    port = int(os.getenv("TRAINSTACK_HTTP_ENV_PORT", "18082"))
    uvicorn.run(app, host=host, port=port)

