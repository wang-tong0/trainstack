from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class Capability(BaseModel):
    gpu: str | None = None
    count: int | None = None


class AcquireLeaseRequest(BaseModel):
    worker_id: str
    run_id: str
    cap: Capability | None = None
    force: bool = False


class WorkerConfig(BaseModel):
    l1_root: str = "/mnt/relay"
    run_id: str
    ckpt_interval_sec: int = 600
    ckpt_keep_last_n: int = 3
    hf_sync_interval_sec: int = 4 * 3600
    hf_repo: str | None = None
    hf_push_on_improve: bool = False


class AcquireLeaseResponse(BaseModel):
    status: Literal["granted", "denied"]
    lease_token: str | None = None
    lease_expires_in_sec: int | None = None
    reason: str | None = None
    config: WorkerConfig | None = None


class RenewLeaseRequest(BaseModel):
    lease_token: str
    worker_id: str


class JobHFStatus(BaseModel):
    last_synced: bool = False
    repo: str | None = None
    revision: str | None = None


class JobReportRequest(BaseModel):
    lease_token: str
    run_id: str
    step: int = 0
    latest_ckpt: str | None = None
    hf: JobHFStatus | None = None
    status: Literal["RUNNING", "PREEMPTED", "FAILED", "COMPLETED"] = "RUNNING"
    msg: str | None = None


class ActiveLease(BaseModel):
    run_id: str
    lease_token: str
    worker_id: str
    expires_at: datetime


class RunStatus(BaseModel):
    run_id: str
    last_reported_step: int = 0
    last_ckpt: str | None = None
    last_hf_repo: str | None = None
    last_hf_revision: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["RUNNING", "PREEMPTED", "FAILED", "COMPLETED"] = "RUNNING"
    msg: str | None = None


class CommanderState(BaseModel):
    active_lease: ActiveLease | None = None
    run_status: dict[str, RunStatus] = Field(default_factory=dict)
