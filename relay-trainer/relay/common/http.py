from __future__ import annotations

import time
from dataclasses import dataclass

import requests


@dataclass
class HttpClient:
    base_url: str
    timeout: int = 15
    retries: int = 5
    backoff_sec: float = 1.0

    def post(self, path: str, payload: dict, headers: dict | None = None) -> requests.Response:
        url = self.base_url.rstrip("/") + path
        error: Exception | None = None
        for i in range(self.retries):
            try:
                resp = requests.post(url, json=payload, headers=headers or {}, timeout=self.timeout)
                if resp.status_code < 500:
                    return resp
                error = RuntimeError(f"server error {resp.status_code}: {resp.text}")
            except requests.RequestException as exc:
                error = exc
            if i < self.retries - 1:
                time.sleep(self.backoff_sec * (2**i))
        if error is None:
            raise RuntimeError(f"request failed: {url}")
        raise RuntimeError(f"request failed: {url}: {error}")
