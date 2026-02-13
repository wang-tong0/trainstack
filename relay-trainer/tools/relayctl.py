from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import requests
import typer
import yaml

app = typer.Typer(help="Relay trainer commander-side helper tool")


@app.command()
def serve(
    host: str = "0.0.0.0",
    port: int = 8080,
    state_path: str = "./commander_state.json",
    lease_seconds: int = 3600,
    shared_secret: str = "",
) -> None:
    os.environ["RELAY_COMMANDER_STATE"] = state_path
    os.environ["RELAY_LEASE_SECONDS"] = str(lease_seconds)
    os.environ["RELAY_SHARED_SECRET"] = shared_secret
    import uvicorn

    uvicorn.run("relay.commander_app:app", host=host, port=port)


@app.command()
def status(commander_url: str = "http://127.0.0.1:8080", state_path: str = "") -> None:
    if state_path:
        path = Path(state_path)
        if not path.exists():
            raise typer.BadParameter(f"state file not found: {state_path}")
        typer.echo(path.read_text(encoding="utf-8"))
        return
    health = requests.get(commander_url.rstrip("/") + "/api/health", timeout=10)
    health.raise_for_status()
    typer.echo(json.dumps(health.json(), indent=2))


@app.command()
def print_lium_command(
    template_id: str,
    pod_name: str,
    volume: str,
    commander_url: str,
    run_id: str,
    mode: str = "sft",
    hf_repo: str = "",
) -> None:
    cmd = (
        f"lium up --name {pod_name} --template_id {template_id} --volume {volume} "
        f"--env COMMANDER_URL={commander_url} --env RUN_ID={run_id} --env MODE={mode}"
    )
    if hf_repo:
        cmd += f" --env HF_REPO={hf_repo}"
    typer.echo(cmd)


def _resolve_path(base: Path, raw: str) -> Path:
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p
    return (base / p).resolve()


def _run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(shlex.quote(x) for x in cmd)}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return proc


def _is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@app.command("launch-stack")
def launch_stack(config: str = typer.Argument(..., help="Path to one-click launch yaml")) -> None:
    """
    One-click launcher:
    - start local commander in background
    - create Lium pod
    - upload worker run.yaml to pod
    - start worker in pod background
    """
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = _resolve_path(Path.cwd(), config)
    if not cfg_path.exists():
        raise typer.BadParameter(f"config not found: {cfg_path}")

    raw_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw_cfg, dict):
        raise typer.BadParameter("top-level config must be a yaml mapping")

    commander_cfg = raw_cfg.get("commander", {}) or {}
    worker_cfg = raw_cfg.get("worker", {}) or {}
    lium_cfg = raw_cfg.get("lium", {}) or {}
    run_cfg = raw_cfg.get("run", {}) or {}

    # 1) start commander in background
    commander_host = str(commander_cfg.get("host", "0.0.0.0"))
    commander_port = int(commander_cfg.get("port", 8080))
    commander_public_url = str(commander_cfg.get("public_url", f"http://127.0.0.1:{commander_port}"))
    commander_state_path = _resolve_path(repo_root, str(commander_cfg.get("state_path", "./commander_state.json")))
    commander_log_path = _resolve_path(repo_root, str(commander_cfg.get("log_path", "./.relay-launch/commander.log")))
    commander_pid_path = _resolve_path(repo_root, str(commander_cfg.get("pid_path", "./.relay-launch/commander.pid")))
    commander_lease_seconds = int(commander_cfg.get("lease_seconds", 3600))
    commander_shared_secret = str(commander_cfg.get("shared_secret", ""))
    commander_python = str(commander_cfg.get("python_bin", "/root/venv/bin/python"))
    commander_wait_sec = int(commander_cfg.get("wait_seconds", 30))
    commander_restart = bool(commander_cfg.get("restart_if_running", False))

    commander_log_path.parent.mkdir(parents=True, exist_ok=True)
    commander_pid_path.parent.mkdir(parents=True, exist_ok=True)
    commander_state_path.parent.mkdir(parents=True, exist_ok=True)

    if commander_pid_path.exists():
        old_pid_raw = commander_pid_path.read_text(encoding="utf-8").strip()
        if old_pid_raw.isdigit() and _is_pid_running(int(old_pid_raw)):
            if commander_restart:
                os.kill(int(old_pid_raw), signal.SIGTERM)
                time.sleep(1)
            else:
                raise RuntimeError(
                    f"commander already running with pid {old_pid_raw}. "
                    "Set commander.restart_if_running=true to restart."
                )

    commander_env = os.environ.copy()
    commander_env["RELAY_COMMANDER_STATE"] = str(commander_state_path)
    commander_env["RELAY_LEASE_SECONDS"] = str(commander_lease_seconds)
    commander_env["RELAY_SHARED_SECRET"] = commander_shared_secret

    with commander_log_path.open("ab") as f:
        commander_proc = subprocess.Popen(
            [
                commander_python,
                "-m",
                "uvicorn",
                "relay.commander_app:app",
                "--host",
                commander_host,
                "--port",
                str(commander_port),
            ],
            cwd=str(repo_root),
            env=commander_env,
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    commander_pid_path.write_text(str(commander_proc.pid), encoding="utf-8")

    health_url = commander_public_url.rstrip("/") + "/api/health"
    started = False
    for _ in range(commander_wait_sec):
        try:
            r = requests.get(health_url, timeout=2)
            if r.ok:
                started = True
                break
        except Exception:
            pass
        time.sleep(1)
    if not started:
        raise RuntimeError(f"commander health check timeout: {health_url}")

    # 2) create lium pod
    template_id = str(lium_cfg.get("template_id", "")).strip()
    if not template_id:
        raise typer.BadParameter("lium.template_id is required")
    pod_name = str(lium_cfg.get("pod_name", "")).strip()
    if not pod_name:
        run_id_for_name = str(run_cfg.get("run_id", "relay-run"))
        pod_name = f"relay-{run_id_for_name[:24]}"

    up_cmd: list[str] = ["lium", "up"]
    executor = str(lium_cfg.get("executor", "")).strip()
    if executor:
        up_cmd.append(executor)
    up_cmd += ["--template_id", template_id, "--name", pod_name]

    volume = str(lium_cfg.get("volume", "")).strip()
    if volume:
        up_cmd += ["--volume", volume]
    ttl = str(lium_cfg.get("ttl", "")).strip()
    if ttl:
        up_cmd += ["--ttl", ttl]
    if bool(lium_cfg.get("yes", True)):
        up_cmd.append("-y")

    _run_cmd(up_cmd)

    ready_timeout = int(lium_cfg.get("ready_timeout_seconds", 300))
    poll_interval = int(lium_cfg.get("poll_interval_seconds", 5))
    deadline = time.time() + ready_timeout
    while True:
        probe = _run_cmd(["lium", "exec", pod_name, "echo READY"], check=False)
        if probe.returncode == 0 and "READY" in probe.stdout:
            break
        if time.time() > deadline:
            raise RuntimeError(f"pod did not become exec-ready in {ready_timeout}s: {pod_name}")
        time.sleep(poll_interval)

    # 3) build/upload worker relay run config
    relay_run_config = worker_cfg.get("relay_run_config")
    if not relay_run_config:
        relay_run_config = {
            "commander_url": commander_public_url,
            "run_id": str(run_cfg.get("run_id", "demo-sft-run")),
            "worker_id": str(run_cfg.get("worker_id", pod_name)),
            "mode": str(run_cfg.get("mode", "sft")),
            "hf_repo": str(run_cfg.get("hf_repo", "")),
            "hf_dry_run": bool(run_cfg.get("hf_dry_run", True)),
            "relay_shared_secret": commander_shared_secret,
            "save_rollout_trajectories": bool(run_cfg.get("save_rollout_trajectories", False)),
            "rollout_trajectory_subdir": str(run_cfg.get("rollout_trajectory_subdir", "rollout")),
            "rollout_trajectory_pattern": str(
                run_cfg.get("rollout_trajectory_pattern", "rollout_{rollout_id:08d}.pt")
            ),
        }

    local_worker_cfg_path = _resolve_path(
        repo_root, str(worker_cfg.get("local_config_path", "./.relay-launch/worker.run.yaml"))
    )
    local_worker_cfg_path.parent.mkdir(parents=True, exist_ok=True)
    local_worker_cfg_path.write_text(yaml.safe_dump(relay_run_config, sort_keys=False), encoding="utf-8")

    remote_worker_cfg_path = str(
        worker_cfg.get("remote_config_path", "/workspace/slime/relay-trainer/configs/run.launch.yaml")
    )
    _run_cmd(["lium", "scp", pod_name, str(local_worker_cfg_path), remote_worker_cfg_path])

    # 4) start worker in pod background
    remote_log_path = str(worker_cfg.get("remote_log_path", "/tmp/relay-worker.log"))
    remote_pid_path = str(worker_cfg.get("remote_pid_path", "/tmp/relay-worker.pid"))
    remote_workdir = str(worker_cfg.get("remote_workdir", "/workspace/slime/relay-trainer"))
    remote_python = str(worker_cfg.get("remote_python_bin", "/root/venv/bin/python"))
    default_worker_cmd = f"{remote_python} -m relay.worker.relay_entry --config {shlex.quote(remote_worker_cfg_path)}"
    worker_command = str(worker_cfg.get("command", default_worker_cmd))
    worker_env = worker_cfg.get("env", {}) or {}
    if not isinstance(worker_env, dict):
        raise typer.BadParameter("worker.env must be a key/value mapping")

    export_items = [("RELAY_RUN_CONFIG", remote_worker_cfg_path), *worker_env.items()]
    export_prefix = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in export_items)
    remote_script = (
        f"mkdir -p {shlex.quote(str(Path(remote_log_path).parent))} "
        f"{shlex.quote(str(Path(remote_pid_path).parent))} && "
        f"cd {shlex.quote(remote_workdir)} && "
        f"nohup env {export_prefix} bash -lc {shlex.quote(worker_command)} "
        f">{shlex.quote(remote_log_path)} 2>&1 < /dev/null & "
        f"echo $! > {shlex.quote(remote_pid_path)} && "
        f"cat {shlex.quote(remote_pid_path)}"
    )
    worker_start = _run_cmd(["lium", "exec", pod_name, remote_script])
    worker_pid = "unknown"
    for line in reversed(worker_start.stdout.strip().splitlines()):
        s = line.strip()
        if s.isdigit():
            worker_pid = s
            break

    worker_ok = False
    if worker_pid != "unknown":
        worker_check = _run_cmd(
            ["lium", "exec", pod_name, f"ps -p {worker_pid} -o pid=,cmd="], check=False
        )
        worker_ok = worker_check.returncode == 0

    summary: dict[str, Any] = {
        "commander": {
            "url": commander_public_url,
            "pid": commander_proc.pid,
            "state_path": str(commander_state_path),
            "log_path": str(commander_log_path),
            "pid_path": str(commander_pid_path),
        },
        "lium": {
            "pod_name": pod_name,
            "template_id": template_id,
        },
        "worker": {
            "pid": worker_pid,
            "running": worker_ok,
            "remote_log_path": remote_log_path,
            "remote_pid_path": remote_pid_path,
            "remote_config_path": remote_worker_cfg_path,
        },
    }
    typer.echo(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()
