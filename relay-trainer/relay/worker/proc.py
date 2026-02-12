from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass


@dataclass
class ManagedProcess:
    process: subprocess.Popen

    def poll(self) -> int | None:
        return self.process.poll()

    def terminate(self) -> None:
        if self.poll() is None:
            self.process.terminate()

    def kill(self) -> None:
        if self.poll() is None:
            self.process.kill()


def launch(cmd: list[str], env: dict[str, str], cwd: str | None = None) -> ManagedProcess:
    proc = subprocess.Popen(cmd, env=env, cwd=cwd)
    return ManagedProcess(process=proc)


def send_usr1(proc: ManagedProcess) -> None:
    if proc.poll() is None:
        os.kill(proc.process.pid, signal.SIGUSR1)
