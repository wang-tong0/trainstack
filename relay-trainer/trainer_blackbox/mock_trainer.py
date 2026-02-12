from __future__ import annotations

import argparse
import json
import signal
import time
from pathlib import Path

STOP = False


def _on_usr1(_signum, _frame):
    # Placeholder for signal-triggered checkpoint in real trainers.
    return


def _on_term(_signum, _frame):
    global STOP
    STOP = True


signal.signal(signal.SIGUSR1, _on_usr1)
signal.signal(signal.SIGTERM, _on_term)
signal.signal(signal.SIGINT, _on_term)


def write_step(staging_root: Path, step: int, mode: str) -> None:
    out = staging_root / f"step_{step:08d}"
    out.mkdir(parents=True, exist_ok=True)
    metrics = {"step": step, "loss": round(1.0 / max(1, step), 6), "mode": mode}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["sft", "rl"], required=True)
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--save-every", type=int, default=1)
    parser.add_argument("--staging-root", required=True)
    args = parser.parse_args()

    staging_root = Path(args.staging_root)

    for step in range(1, args.max_steps + 1):
        if STOP:
            break
        if step % args.save_every == 0:
            write_step(staging_root, step, args.mode)
        time.sleep(1)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
