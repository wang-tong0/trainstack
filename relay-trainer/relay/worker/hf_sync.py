from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_snapshot(latest_ckpt: Path, run_root: Path) -> Path:
    if not latest_ckpt.exists():
        raise FileNotFoundError(f"latest checkpoint missing: {latest_ckpt}")
    tmp_dir = Path(tempfile.mkdtemp(prefix="relay_hf_snapshot_"))
    snapshot = tmp_dir / "snapshot"
    shutil.copytree(latest_ckpt, snapshot / "ckpt")

    state = run_root / "state.json"
    if state.exists():
        (snapshot / "state.json").write_text(state.read_text(encoding="utf-8"), encoding="utf-8")
    events = run_root / "events.log"
    if events.exists():
        (snapshot / "events.log").write_text(events.read_text(encoding="utf-8"), encoding="utf-8")
    return snapshot


def sync_snapshot(
    snapshot_dir: Path,
    run_root: Path,
    repo_id: str,
    revision_branch: str = "main",
    dry_run: bool = False,
) -> str:
    last_synced = run_root / "hf" / "last_synced.json"
    last_synced.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        revision = f"dry-run-{int(datetime.now(timezone.utc).timestamp())}"
    else:
        api = HfApi(token=os.getenv("HF_TOKEN"))
        api.create_repo(repo_id=repo_id, repo_type="model", exist_ok=True, private=True)
        api.upload_folder(
            repo_id=repo_id,
            repo_type="model",
            folder_path=str(snapshot_dir),
            path_in_repo="",
            revision=revision_branch,
            commit_message="relay milestone snapshot",
        )
        info = api.model_info(repo_id=repo_id, revision=revision_branch)
        revision = info.sha

    payload = {
        "repo": repo_id,
        "revision": revision,
        "at": _utc_now(),
    }
    last_synced.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return revision
