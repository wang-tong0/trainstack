from fastapi.testclient import TestClient

from relay import commander_app
from relay.common.schema import CommanderState


def test_lease_lifecycle():
    commander_app.store.state = CommanderState()
    commander_app.store.save()

    client = TestClient(commander_app.app)

    acquire = client.post(
        "/api/lease/acquire",
        json={"worker_id": "w1", "run_id": "r1", "cap": {"gpu": "cpu", "count": 0}},
    )
    assert acquire.status_code == 200
    payload = acquire.json()
    assert payload["status"] == "granted"
    token = payload["lease_token"]

    acquire2 = client.post(
        "/api/lease/acquire",
        json={"worker_id": "w2", "run_id": "r1", "cap": {"gpu": "cpu", "count": 0}},
    )
    assert acquire2.status_code == 200
    assert acquire2.json()["status"] == "denied"

    renew = client.post("/api/lease/renew", json={"lease_token": token, "worker_id": "w1"})
    assert renew.status_code == 200

    report = client.post(
        "/api/job/report",
        json={
            "lease_token": token,
            "run_id": "r1",
            "step": 3,
            "latest_ckpt": "step_00000003",
            "status": "RUNNING",
            "hf": {"last_synced": False, "repo": None, "revision": None},
        },
    )
    assert report.status_code == 200
