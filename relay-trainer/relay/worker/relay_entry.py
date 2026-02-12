from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml

from relay.common.http import HttpClient
from relay.worker.ckpt import (
    append_event,
    ensure_run_dirs,
    finalize_external_checkpoint,
    latest_valid_step,
    write_state,
)
from relay.worker.hf_sync import make_snapshot, sync_snapshot
from relay.worker.proc import launch

STOP = False


def _on_term(_signum, _frame):
    global STOP
    STOP = True


signal.signal(signal.SIGTERM, _on_term)
signal.signal(signal.SIGINT, _on_term)


def load_run_config(path: str | None) -> dict:
    cfg = {}
    if path:
        cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return cfg


def get_env_or_cfg(cfg: dict, key: str, default=None):
    env_key = key.upper()
    if env_key in os.environ:
        return os.environ[env_key]
    return cfg.get(key, default)


def run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.getenv("RELAY_RUN_CONFIG", "configs/run.yaml"))
    args = parser.parse_args()

    cfg = load_run_config(args.config if Path(args.config).exists() else None)
    commander_url = get_env_or_cfg(cfg, "commander_url")
    if not commander_url:
        print("missing commander_url", file=sys.stderr)
        return 2

    worker_id = get_env_or_cfg(cfg, "worker_id", os.getenv("HOSTNAME", "relay-worker"))
    run_id = get_env_or_cfg(cfg, "run_id", "relay-run")
    shared_secret = get_env_or_cfg(cfg, "relay_shared_secret", os.getenv("RELAY_SHARED_SECRET", ""))
    mode = get_env_or_cfg(cfg, "mode", "sft")
    hf_repo = get_env_or_cfg(cfg, "hf_repo", "")
    hf_dry_run = str(get_env_or_cfg(cfg, "hf_dry_run", "true")).lower() == "true"

    client = HttpClient(base_url=commander_url)
    acquire_headers = {"X-Relay-Secret": shared_secret} if shared_secret else None
    acquire_payload = {"worker_id": worker_id, "run_id": run_id, "cap": {"gpu": "cpu", "count": 0}}

    while True:
        try:
            acquire = client.post("/api/lease/acquire", acquire_payload, headers=acquire_headers)
            data = acquire.json()
            if data.get("status") == "granted":
                break
            time.sleep(5)
        except Exception:
            time.sleep(5)

    lease_token = data["lease_token"]
    worker_cfg = data["config"]
    l1_root = Path(worker_cfg["l1_root"]) / "runs" / run_id
    dirs = ensure_run_dirs(l1_root)

    append_event(l1_root, "acquire", worker_id=worker_id, run_id=run_id)

    valid = latest_valid_step(dirs["ckpt_root"])
    if valid is not None:
        resume_from = str(valid)
        append_event(l1_root, "resume_l1", checkpoint=valid.name)
    else:
        resume_from = ""
        append_event(l1_root, "resume_cold_start")

    cmd = ["bash", "trainer_blackbox/launch_sft.sh" if mode == "sft" else "trainer_blackbox/launch_rl.sh"]
    env = os.environ.copy()
    env["RELAY_RUN_ROOT"] = str(l1_root)
    env["RELAY_CKPT_STAGING_ROOT"] = str(dirs["staging_root"])
    env["RELAY_RESUME_FROM"] = resume_from

    proc = launch(cmd, env=env, cwd=str(Path(__file__).resolve().parents[2]))
    renew_interval = 45
    report_interval = 90
    hf_interval = int(worker_cfg["hf_sync_interval_sec"])
    keep_last_n = int(worker_cfg["ckpt_keep_last_n"])

    next_renew = 0.0
    next_report = 0.0
    next_hf = time.time() + hf_interval
    last_step_name = valid.name if valid else None
    last_hf_revision = None

    while True:
        now = time.time()
        if STOP:
            append_event(l1_root, "sigterm")
            write_state(
                l1_root,
                {
                    "status": "PREEMPTED",
                    "latest_ckpt": last_step_name,
                    "last_hf_revision": last_hf_revision,
                    "updated_at": int(now),
                },
            )
            try:
                client.post(
                    "/api/job/report",
                    {
                        "lease_token": lease_token,
                        "run_id": run_id,
                        "step": int((last_step_name or "step_0").split("_")[-1]),
                        "latest_ckpt": last_step_name,
                        "status": "PREEMPTED",
                        "hf": {"last_synced": bool(last_hf_revision), "repo": hf_repo, "revision": last_hf_revision},
                    },
                )
            except Exception:
                pass
            proc.terminate()
            return 0

        for staged in sorted(dirs["staging_root"].glob("step_*")):
            step_name = staged.name
            final = finalize_external_checkpoint(dirs["staging_root"], dirs["ckpt_root"], step_name, keep_last_n)
            last_step_name = final.name
            append_event(l1_root, "ckpt_saved", checkpoint=last_step_name)
            write_state(
                l1_root,
                {
                    "status": "RUNNING",
                    "latest_ckpt": last_step_name,
                    "last_hf_revision": last_hf_revision,
                    "updated_at": int(now),
                },
            )

        if now >= next_renew:
            client.post("/api/lease/renew", {"lease_token": lease_token, "worker_id": worker_id})
            next_renew = now + renew_interval

        if now >= next_report:
            step = int((last_step_name or "step_0").split("_")[-1])
            client.post(
                "/api/job/report",
                {
                    "lease_token": lease_token,
                    "run_id": run_id,
                    "step": step,
                    "latest_ckpt": last_step_name,
                    "status": "RUNNING",
                    "hf": {"last_synced": bool(last_hf_revision), "repo": hf_repo or None, "revision": last_hf_revision},
                },
            )
            next_report = now + report_interval

        if hf_repo and last_step_name and now >= next_hf:
            latest = dirs["ckpt_root"] / last_step_name
            snapshot = make_snapshot(latest, l1_root)
            try:
                last_hf_revision = sync_snapshot(snapshot, l1_root, hf_repo, dry_run=hf_dry_run)
                append_event(l1_root, "hf_synced", repo=hf_repo, revision=last_hf_revision)
            finally:
                subprocess.run(["rm", "-rf", str(snapshot.parent)], check=False)
            next_hf = now + hf_interval

        code = proc.poll()
        if code is not None:
            final_status = "COMPLETED" if code == 0 else "FAILED"
            if hf_repo and last_step_name and not last_hf_revision:
                latest = dirs["ckpt_root"] / last_step_name
                snapshot = make_snapshot(latest, l1_root)
                try:
                    last_hf_revision = sync_snapshot(snapshot, l1_root, hf_repo, dry_run=hf_dry_run)
                    append_event(l1_root, "hf_synced", repo=hf_repo, revision=last_hf_revision)
                finally:
                    subprocess.run(["rm", "-rf", str(snapshot.parent)], check=False)
            write_state(
                l1_root,
                {
                    "status": final_status,
                    "latest_ckpt": last_step_name,
                    "last_hf_revision": last_hf_revision,
                    "updated_at": int(now),
                    "exit_code": code,
                },
            )
            try:
                client.post(
                    "/api/job/report",
                    {
                        "lease_token": lease_token,
                        "run_id": run_id,
                        "step": int((last_step_name or "step_0").split("_")[-1]),
                        "latest_ckpt": last_step_name,
                        "status": final_status,
                        "hf": {"last_synced": bool(last_hf_revision), "repo": hf_repo or None, "revision": last_hf_revision},
                    },
                )
            except Exception:
                pass
            return code

        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(run())
