from __future__ import annotations

from pathlib import Path

import typer

from relay.worker.hf_sync import make_snapshot, sync_snapshot

app = typer.Typer(help="Push latest relay checkpoint to Hugging Face")


@app.command()
def main(
    run_root: str = typer.Option(..., help="Run root, e.g. /mnt/relay/runs/<run_id>"),
    repo_id: str = typer.Option(..., help="HF model repo id"),
    branch: str = typer.Option("main", help="Target branch"),
    dry_run: bool = typer.Option(False, help="Do not upload, only generate revision metadata"),
) -> None:
    root = Path(run_root)
    latest = root / "ckpt" / "latest"
    if latest.is_symlink():
        latest = latest.resolve()
    snapshot = make_snapshot(latest, root)
    try:
        revision = sync_snapshot(snapshot, root, repo_id=repo_id, revision_branch=branch, dry_run=dry_run)
    finally:
        import shutil

        shutil.rmtree(snapshot.parent, ignore_errors=True)
    typer.echo(revision)


if __name__ == "__main__":
    app()
