# relay-trainer (independent project, slime as dependency)

Chinese version: `README_zh.md`

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
- `RELAY_SAVE_ROLLOUT_TRAJECTORIES` (`1`/`0`, set by worker config)
- `RELAY_ROLLOUT_TRAJECTORY_ROOT` (run-volume path for rollout traces)
- `RELAY_ROLLOUT_TRAJECTORY_PATTERN` (slime `--save-debug-rollout-data` pattern)

Minimal `configs/run.yaml` template:

```yaml
commander_url: "http://<cpu-server>:8080"
run_id: "lium-demo-sft"
worker_id: "lium-pod-001"
mode: "sft"
hf_repo: "<user>/<private_repo>"
hf_dry_run: false
relay_shared_secret: "<SECRET>"
save_rollout_trajectories: true
rollout_trajectory_subdir: "rollout"
rollout_trajectory_pattern: "rollout_{rollout_id:08d}.pt"
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

For RL trajectory auditing, consume the relay env vars in your RL command/script:

```bash
--save-debug-rollout-data "${RELAY_ROLLOUT_TRAJECTORY_ROOT}/${RELAY_ROLLOUT_TRAJECTORY_PATTERN}"
```

When `save_rollout_trajectories: true`, worker will include `<run_root>/<rollout_trajectory_subdir>` in each HF snapshot upload.

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

## 8. One-click launch (commander + lium worker)

Use one yaml config to:
- start local commander in background
- create Lium pod from template
- upload worker run config into pod
- start worker process in pod background

```bash
cd relay-trainer
cp configs/launch_stack.example.yaml configs/launch_stack.yaml
# edit configs/launch_stack.yaml (especially commander.public_url / template / volume)
python tools/relayctl.py launch-stack configs/launch_stack.yaml
```

After launch, the command prints:
- commander pid/log/state path
- pod name/template
- worker pid/log/config path

### 8.1 YAML config reference (`configs/launch_stack.yaml`)

Top-level sections:
- `commander`: local CPU commander process config
- `lium`: how to create worker pod
- `run`: relay run semantic config (mode/run_id/hf/etc)
- `worker`: how to start worker process inside pod

#### `commander` fields
- `host` (default `0.0.0.0`): uvicorn bind host.
- `port` (default `8080`): uvicorn bind port.
- `public_url` (required in most real cases): worker pod can access this URL.  
  Example: `http://<commander-public-ip>:8080`.
- `state_path` (default `./commander_state.json`): lease/state persistence file.
- `log_path` (default `./.relay-launch/commander.log`): local commander log.
- `pid_path` (default `./.relay-launch/commander.pid`): local commander pid file.
- `lease_seconds` (default `3600`): lease ttl used by commander.
- `shared_secret` (default empty): relay shared secret, must match worker side.
- `python_bin` (default `/root/venv/bin/python`): python used to start commander.
- `wait_seconds` (default `30`): health-check timeout after commander launch.
- `restart_if_running` (default `false`): if `true`, kill old commander pid and restart.

#### `lium` fields
- `template_id` (required): Lium template name or ID, e.g. `relay-trainer`.
- `pod_name` (optional): pod name. If omitted, auto-generated from `run.run_id`.
- `executor` (optional): pass-through first positional arg of `lium up`.
- `volume` (optional but recommended): e.g. `new:name=relay-auto-demo` or `id:<HUID>`.
- `ttl` (optional): pod lifetime, e.g. `2h`.
- `yes` (default `true`): auto confirm `lium up`.
- `ready_timeout_seconds` (default `300`): max wait for pod exec-ready.
- `poll_interval_seconds` (default `5`): readiness poll interval.

#### `run` fields
- `run_id` (default `demo-sft-run`): logical run id.
- `mode` (default `sft`): `sft` or `rl`.
- `worker_id` (default pod name): worker identity reported to commander.
- `hf_repo` (default empty): HF target repo.
- `hf_dry_run` (default `true`): if `true`, no real HF upload.
- `save_rollout_trajectories` (default `false`): whether to persist rollout traces.
- `rollout_trajectory_subdir` (default `rollout`): relative subdir under run root.
- `rollout_trajectory_pattern` (default `rollout_{rollout_id:08d}.pt`): rollout file pattern.

#### `worker` fields
- `relay_run_config` (optional): if provided, uploaded directly as worker `run.yaml`; `run` section is ignored for generation.
- `local_config_path` (default `./.relay-launch/worker.run.yaml`): generated local temp config.
- `remote_config_path` (default `/workspace/slime/relay-trainer/configs/run.launch.yaml`): uploaded config path in pod.
- `remote_workdir` (default `/workspace/slime/relay-trainer`): worker process cwd in pod.
- `remote_python_bin` (default `/root/venv/bin/python`): python used to run worker.
- `remote_log_path` (default `/tmp/relay-worker.log`): worker log in pod.
- `remote_pid_path` (default `/tmp/relay-worker.pid`): worker pid in pod.
- `command` (optional): custom startup command.  
  Default: `python -m relay.worker.relay_entry --config <remote_config_path>`.
- `env` (default `{}`): extra env vars injected into worker process.

### 8.2 Concrete startup flow

1. Prepare config
```bash
cd /home/ubuntu/slime/relay-trainer
cp configs/launch_stack.example.yaml configs/launch_stack.yaml
```

2. Edit critical fields in `configs/launch_stack.yaml`
- `commander.public_url`: must be reachable from Lium pod.
- `lium.template_id`: your template (e.g. `relay-trainer`).
- `lium.volume`: use persistent volume if you want checkpoints retained.
- `run.mode`: choose `sft` or `rl`.
- `run.hf_repo` and `run.hf_dry_run`: decide whether to upload to HF.

3. Launch stack
```bash
python tools/relayctl.py launch-stack configs/launch_stack.yaml
```

4. What `launch-stack` actually does
- Starts local commander in background (`uvicorn relay.commander_app:app`).
- Waits until `GET /api/health` is OK.
- Calls `lium up ...` to create pod.
- Polls `lium exec <pod> "echo READY"` until pod is ready.
- Uploads generated worker config to pod (`lium scp`).
- Starts worker inside pod with `nohup ... &`, records pid.
- Prints a JSON summary for commander/pod/worker status.

### 8.3 Verify and operate after launch

Check commander:
```bash
python tools/relayctl.py status --commander-url http://127.0.0.1:8080
cat ./.relay-launch/commander.pid
tail -n 100 ./.relay-launch/commander.log
```

Check worker pod/process:
```bash
lium ps
lium exec <pod_name> 'cat /tmp/relay-worker.pid && ps -p $(cat /tmp/relay-worker.pid) -o pid=,cmd='
lium exec <pod_name> 'tail -n 200 /tmp/relay-worker.log'
```

Check artifacts in pod volume:
```bash
lium exec <pod_name> 'ls -lah /mnt || true'
lium exec <pod_name> 'find /root/lium_min -maxdepth 3 -type d | head -n 40'
```

Stop stack manually:
```bash
# stop commander
kill $(cat ./.relay-launch/commander.pid)

# stop worker (inside pod)
lium exec <pod_name> 'kill $(cat /tmp/relay-worker.pid)'

# optional: terminate pod
lium rm <pod_name>
```

### 8.4 LiveWeb-Arena examples (SFT / RL)

Two ready-to-edit examples are provided:
- `configs/launch_stack.liveweb_sft.example.yaml`
- `configs/launch_stack.liveweb_rl.example.yaml`

Use one of them as your launch config:

```bash
cd /home/ubuntu/slime/relay-trainer
cp configs/launch_stack.liveweb_sft.example.yaml configs/launch_stack.yaml
# or:
# cp configs/launch_stack.liveweb_rl.example.yaml configs/launch_stack.yaml
python tools/relayctl.py launch-stack configs/launch_stack.yaml
```

Notes:
- These examples assume your pod/container can import `trainstack_plugins.http_env.*`
  and can access `liveweb-arena` runtime (for HTTP env server side).
- In both examples, `worker.env` includes:
  - `LIVEWEB_ARENA_ROOT`
  - `TRAINSTACK_HTTP_ENV_URL`
  - `TRAINSTACK_LLM_URL`
  - `PYTHONPATH` for slime + trainstack plugin + liveweb
- `SLIME_SFT_CMD` / `SLIME_RL_CMD` are intentionally written as templates.
  Replace the command body with your real slime training command that enables:
  `--custom-generate-function-path trainstack_plugins.http_env.adapter.generate`
