from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Header, HTTPException

from relay.common.schema import (
    AcquireLeaseRequest,
    AcquireLeaseResponse,
    ActiveLease,
    CommanderState,
    JobReportRequest,
    RenewLeaseRequest,
    RunStatus,
    WorkerConfig,
)

STATE_PATH = Path(os.getenv("RELAY_COMMANDER_STATE", "./commander_state.json"))
LEASE_SECONDS = int(os.getenv("RELAY_LEASE_SECONDS", "3600"))
SHARED_SECRET = os.getenv("RELAY_SHARED_SECRET", "")


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = Lock()
        self.state = CommanderState()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.state = CommanderState.model_validate(raw)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.state.model_dump_json(indent=2), encoding="utf-8")

    def with_lock(self):
        return self.lock


store = StateStore(STATE_PATH)
app = FastAPI(title="Relay Commander", version="0.1.0")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _lease_expired(lease: ActiveLease | None) -> bool:
    if lease is None:
        return True
    return lease.expires_at <= now_utc()


def _assert_secret(header_secret: str | None) -> None:
    if not SHARED_SECRET:
        return
    if header_secret != SHARED_SECRET:
        raise HTTPException(status_code=401, detail="invalid shared secret")


def _default_config(run_id: str) -> WorkerConfig:
    return WorkerConfig(
        l1_root=os.getenv("RELAY_L1_ROOT", "/mnt/relay"),
        run_id=run_id,
        ckpt_interval_sec=int(os.getenv("RELAY_CKPT_INTERVAL", "600")),
        ckpt_keep_last_n=int(os.getenv("RELAY_CKPT_KEEP_LAST_N", "3")),
        hf_sync_interval_sec=int(os.getenv("RELAY_HF_SYNC_INTERVAL", str(4 * 3600))),
        hf_repo=os.getenv("RELAY_HF_REPO") or None,
        hf_push_on_improve=os.getenv("RELAY_HF_PUSH_ON_IMPROVE", "false").lower() == "true",
    )


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/lease/acquire", response_model=AcquireLeaseResponse)
def acquire_lease(req: AcquireLeaseRequest, x_relay_secret: str | None = Header(default=None)) -> AcquireLeaseResponse:
    _assert_secret(x_relay_secret)
    with store.with_lock():
        lease = store.state.active_lease
        if not _lease_expired(lease):
            if req.force:
                store.state.active_lease = None
            else:
                return AcquireLeaseResponse(status="denied", reason="active lease exists")

        token = secrets.token_hex(16)
        active = ActiveLease(
            run_id=req.run_id,
            lease_token=token,
            worker_id=req.worker_id,
            expires_at=now_utc() + timedelta(seconds=LEASE_SECONDS),
        )
        store.state.active_lease = active
        store.state.run_status.setdefault(req.run_id, RunStatus(run_id=req.run_id))
        store.save()
        return AcquireLeaseResponse(
            status="granted",
            lease_token=token,
            lease_expires_in_sec=LEASE_SECONDS,
            config=_default_config(req.run_id),
        )


@app.post("/api/lease/renew")
def renew_lease(req: RenewLeaseRequest) -> dict:
    with store.with_lock():
        lease = store.state.active_lease
        if lease is None or _lease_expired(lease):
            raise HTTPException(status_code=409, detail="lease missing or expired")
        if lease.lease_token != req.lease_token or lease.worker_id != req.worker_id:
            raise HTTPException(status_code=403, detail="lease token mismatch")

        lease.expires_at = now_utc() + timedelta(seconds=LEASE_SECONDS)
        store.state.active_lease = lease
        store.save()
    return {"ok": True, "lease_expires_in_sec": LEASE_SECONDS}


@app.post("/api/job/report")
def report(req: JobReportRequest) -> dict:
    with store.with_lock():
        lease = store.state.active_lease
        if lease is None or _lease_expired(lease):
            raise HTTPException(status_code=409, detail="lease missing or expired")
        if lease.lease_token != req.lease_token:
            raise HTTPException(status_code=403, detail="lease token mismatch")

        status = store.state.run_status.get(req.run_id, RunStatus(run_id=req.run_id))
        status.last_reported_step = req.step
        status.last_ckpt = req.latest_ckpt
        status.updated_at = now_utc()
        status.status = req.status
        status.msg = req.msg
        if req.hf:
            status.last_hf_repo = req.hf.repo
            status.last_hf_revision = req.hf.revision
        store.state.run_status[req.run_id] = status
        if req.status in {"COMPLETED", "FAILED"} and lease.lease_token == req.lease_token:
            store.state.active_lease = None
        store.save()
    return {"ok": True}


def main() -> None:
    import uvicorn

    uvicorn.run("relay.commander_app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))


if __name__ == "__main__":
    main()
