# relay-trainer (independent project, slime as dependency)

This project implements the Relay-Training MVP from `design.md`:

- Commander (CPU service): lease arbitration + run metadata
- Worker (Lium pod container): acquire/recover/train/watchdog/checkpoint/HF sync
- Trainer blackbox launcher: supports `sft` and `rl`
- Docker image and entrypoint for Lium templates
- CPU-side Python tool (`tools/relayctl.py`)

## 1. Project layout

```text
relay-trainer/
├── configs/run.yaml
├── docker/
│   ├── Dockerfile
│   └── entrypoint.sh
├── relay/
│   ├── commander_app.py
│   ├── common/
│   │   ├── http.py
│   │   └── schema.py
│   └── worker/
│       ├── ckpt.py
│       ├── hf_sync.py
│       ├── proc.py
│       └── relay_entry.py
├── tests/
├── tools/relayctl.py
└── trainer_blackbox/
    ├── launch_rl.sh
    ├── launch_sft.sh
    └── mock_trainer.py
```

## 2. Local CPU test (already validated)

```bash
cd relay-trainer
pip install -e '.[test]'
pytest -q
```

`tests/test_worker_integration.py` validates:
- commander acquire/renew/report
- worker SFT run
- worker RL run with same `run_id` (resume path)
- atomic checkpoint + `latest` symlink
- HF sync dry-run metadata write

## 3. Run commander on CPU server

```bash
cd relay-trainer
python tools/relayctl.py serve --host 0.0.0.0 --port 8080 --state-path ./commander_state.json --shared-secret '<SECRET>'
```

## 4. Build/push Lium image

```bash
cd relay-trainer
docker build -t <dockerhub_user>/relay-trainer:0.1.0 -f docker/Dockerfile .
docker push <dockerhub_user>/relay-trainer:0.1.0
```

## 5. Run on Lium pod

Use your template pointing to this image, and mount volume to `/mnt`.

Environment variables:
- `RELAY_RUN_CONFIG` (default `configs/run.yaml`)
- `COMMANDER_URL`
- `RUN_ID`
- `MODE` (`sft` or `rl`)
- `RELAY_SHARED_SECRET`
- `HF_TOKEN` (already present in your environment)
- `HF_REPO` (private model repo)

Minimal `configs/run.yaml` template:

```yaml
commander_url: "http://<cpu-server>:8080"
run_id: "lium-demo-sft"
worker_id: "lium-pod-001"
mode: "sft"
hf_repo: "<user>/<private_repo>"
hf_dry_run: false
relay_shared_secret: "<SECRET>"
```

## 6. Plug real slime SFT/RL commands

`launch_sft.sh` and `launch_rl.sh` use mock trainer by default.

To use slime in Lium container, set:

```bash
export SLIME_SFT_CMD='bash /workspace/slime/scripts/run-qwen3-4B-base-sft.sh'
export SLIME_RL_CMD='bash /workspace/slime/scripts/run-qwen2.5-0.5B-reproducibility.sh'
```

Relay runtime exports:
- `RELAY_OUTPUT_DIR`
- `RELAY_RESUME_FROM`

You can read these vars in your slime wrapper scripts to map save/load paths into `/mnt/relay/runs/<run_id>/...`.

## 7. Commander helper commands

```bash
# health check
python tools/relayctl.py status --commander-url http://127.0.0.1:8080

# print lium up template command
python tools/relayctl.py print-lium-command \
  --template-id <template_id> \
  --pod-name relay-sft-01 \
  --volume id:<volume_huid> \
  --commander-url http://<cpu-server>:8080 \
  --run-id lium-demo-sft \
  --mode sft \
  --hf-repo <user>/<private_repo>
```
