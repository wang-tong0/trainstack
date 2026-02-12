from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import requests
import yaml


def wait_health(url: str, timeout: float = 30.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            resp = requests.get(url + "/api/health", timeout=2)
            if resp.ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise RuntimeError("commander health check timeout")


def test_worker_sft_and_rl(tmp_path: Path):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())
    env["RELAY_COMMANDER_STATE"] = str(tmp_path / "commander_state.json")
    l1_root = tmp_path / "mnt" / "relay"
    env["RELAY_L1_ROOT"] = str(l1_root)

    commander = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "relay.commander_app:app", "--port", "18080"],
        cwd=str(Path.cwd()),
        env=env,
    )
    try:
        wait_health("http://127.0.0.1:18080")

        cfg = {
            "commander_url": "http://127.0.0.1:18080",
            "run_id": "run-demo",
            "worker_id": "worker-1",
            "mode": "sft",
            "hf_repo": "demo/private-relay",
            "hf_dry_run": True,
        }
        cfg_path = tmp_path / "run.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

        worker_env = os.environ.copy()
        worker_env["PYTHONPATH"] = str(Path.cwd())
        worker_env["MOCK_MAX_STEPS"] = "2"
        worker_env["RELAY_L1_ROOT"] = str(l1_root)
        worker_env["RELAY_HF_SYNC_INTERVAL"] = "2"

        proc1 = subprocess.run(
            [sys.executable, "-m", "relay.worker.relay_entry", "--config", str(cfg_path)],
            cwd=str(Path.cwd()),
            env=worker_env,
            check=False,
            timeout=120,
        )
        assert proc1.returncode == 0

        cfg["mode"] = "rl"
        cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

        proc2 = subprocess.run(
            [sys.executable, "-m", "relay.worker.relay_entry", "--config", str(cfg_path)],
            cwd=str(Path.cwd()),
            env=worker_env,
            check=False,
            timeout=120,
        )
        assert proc2.returncode == 0

        run_root = l1_root / "runs" / "run-demo"
        latest = run_root / "ckpt" / "latest"
        assert latest.exists()
        state = (run_root / "state.json").read_text(encoding="utf-8")
        assert '"status": "COMPLETED"' in state
        assert (run_root / "hf" / "last_synced.json").exists()
    finally:
        commander.terminate()
        commander.wait(timeout=10)
