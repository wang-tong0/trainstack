from __future__ import annotations

import json
import os
import shutil
from hashlib import sha256
from pathlib import Path


def ensure_run_dirs(run_root: Path) -> dict[str, Path]:
    dirs = {
        "run_root": run_root,
        "ckpt_root": run_root / "ckpt",
        "staging_root": run_root / "ckpt" / "_staging",
        "hf_root": run_root / "hf",
        "logs_root": run_root / "logs",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def _file_sha256(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def build_manifest(step_dir: Path) -> dict:
    files = []
    for path in sorted(step_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(step_dir).as_posix()
            files.append({"path": rel, "size": path.stat().st_size, "sha256": _file_sha256(path)})
    return {"file_count": len(files), "files": files}


def save_manifest(step_dir: Path) -> None:
    manifest = build_manifest(step_dir)
    (step_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def verify_step_dir(step_dir: Path) -> bool:
    manifest_file = step_dir / "manifest.json"
    if not manifest_file.exists():
        return False
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    for item in data.get("files", []):
        file_path = step_dir / item["path"]
        if not file_path.exists() or not file_path.is_file():
            return False
        if file_path.stat().st_size != item["size"]:
            return False
        if _file_sha256(file_path) != item["sha256"]:
            return False
    return True


def list_step_dirs(ckpt_root: Path) -> list[Path]:
    return sorted(
        [p for p in ckpt_root.glob("step_*") if p.is_dir()],
        key=lambda p: int(p.name.split("_")[-1]),
    )


def latest_valid_step(ckpt_root: Path) -> Path | None:
    for step_dir in reversed(list_step_dirs(ckpt_root)):
        if verify_step_dir(step_dir):
            return step_dir
    return None


def update_latest_symlink(ckpt_root: Path, step_dir: Path) -> None:
    target = step_dir.name
    latest = ckpt_root / "latest"
    tmp = ckpt_root / ".latest.tmp"
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    os.symlink(target, tmp)
    os.replace(tmp, latest)


def prune_old_ckpt(ckpt_root: Path, keep_last_n: int) -> None:
    steps = list_step_dirs(ckpt_root)
    for old in steps[:-keep_last_n]:
        shutil.rmtree(old, ignore_errors=True)


def finalize_external_checkpoint(staging_root: Path, ckpt_root: Path, step_name: str, keep_last_n: int) -> Path:
    src = staging_root / step_name
    if not src.exists():
        raise FileNotFoundError(f"staging checkpoint missing: {src}")
    save_manifest(src)
    dst = ckpt_root / step_name
    if dst.exists():
        # Allow idempotent step names from external trainers on resume.
        if verify_step_dir(dst):
            shutil.rmtree(src, ignore_errors=True)
            update_latest_symlink(ckpt_root, dst)
            prune_old_ckpt(ckpt_root, keep_last_n)
            return dst
        shutil.rmtree(dst, ignore_errors=True)
    os.replace(src, dst)
    update_latest_symlink(ckpt_root, dst)
    prune_old_ckpt(ckpt_root, keep_last_n)
    return dst


def write_state(run_root: Path, payload: dict) -> None:
    path = run_root / "state.json"
    tmp = run_root / "state.json.tmp"
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def append_event(run_root: Path, event: str, **kwargs) -> None:
    log_path = run_root / "events.log"
    msg = {"event": event, **kwargs}
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=True) + "\n")
