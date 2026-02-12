from __future__ import annotations

import json
import os
from pathlib import Path

import requests
import typer

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


if __name__ == "__main__":
    app()
