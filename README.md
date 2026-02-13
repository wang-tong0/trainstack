# trainstack

`trainstack` is an orchestration repository for building production training workflows on top of upstream `slime`, while keeping upstream code clean and easy to upgrade.

Chinese README: `README_zh.md`

## Why this repository exists

Teams often need to:
- integrate custom environments (for example HTTP-based environments like LiveWeb-Arena),
- run commander/worker style distributed training on Lium,
- keep deployment scripts and operational docs close to code.

Doing all of that by directly modifying upstream `slime` makes upgrades painful.  
`trainstack` solves this by putting project logic in separate modules and keeping `slime/` as a submodule dependency.

## What you can do with trainstack

- Run baseline slime training through wrappers:
  - `python train.py ...`
  - `python train_async.py ...`
- Run commander/worker orchestration with `relay-trainer/`.
- Extend training with project plugins under `trainstack_plugins/`.
- Integrate external environments through HTTP protocol (decoupled from trainer runtime).

## Quick start

```bash
git clone git@github.com:wang-tong0/trainstack.git
cd trainstack
git submodule update --init --recursive
```

Optional install:

```bash
python -m pip install -e .
python -m pip install -e relay-trainer
```

## End-to-end quickstart (fresh machine, Lium + HF)

This section assumes you start from zero and want to:
1. run SFT on Lium,
2. run RL on Lium,
3. sync checkpoints to Hugging Face.

### 1. Prerequisites

- Python 3.10+ and `git`
- Docker installed and logged in:
  [Get Docker](https://docs.docker.com/get-started/get-docker/),
  [docker login](https://docs.docker.com/reference/cli/docker/login/).
  Verify:
  ```bash
  docker --version
  docker info | grep -i Username
  ```
- Lium CLI installed and initialized:
  [Lium docs](https://docs.lium.ai/) and
  [lium-cli on PyPI](https://pypi.org/project/lium-cli/).
  Verify:
  ```bash
  lium --version
  test -f ~/.lium/config.ini && echo "lium config ok"
  ```
- Hugging Face token configured:
  [HF access tokens](https://huggingface.co/settings/tokens).
  Verify:
  ```bash
  test -s ~/.cache/huggingface/token && echo "hf token cache ok"
  ```
- A Lium template pointing to your relay-trainer image.
  Verify:
  ```bash
  lium templates relay-trainer
  ```
  The template output should show your expected image/tag (for example `<dockerhub_user>/relay-trainer:<tag>`).

### 2. Build and push training image

```bash
cd trainstack
docker build -f relay-trainer/docker/Dockerfile -t <dockerhub_user>/relay-trainer:<tag> .
docker push <dockerhub_user>/relay-trainer:<tag>
```

Update your Lium template image/tag to this pushed image.

### 3. Prepare one-click launch config

```bash
cd relay-trainer
cp configs/launch_stack.example.yaml configs/launch_stack.yaml
```

Edit `configs/launch_stack.yaml`:

- `commander.public_url`: public URL reachable from Lium pod
- `commander.shared_secret`: shared secret for commander/worker
- `lium.template_id`: your Lium template
- `lium.volume`: persistent volume (`new:name=...` or `id:<huid>`)
- `run.hf_repo`: your HF model repo (e.g. `yourname/trainstack-demo`)
- `run.hf_dry_run`: set `false` for real upload

For real training (instead of mock trainer), set your slime commands under `worker.env`:

```yaml
worker:
  env:
    SLIME_SFT_CMD: "bash /workspace/slime/scripts/run-qwen3-4B-base-sft.sh"
    SLIME_RL_CMD: "bash /workspace/slime/scripts/run-qwen2.5-0.5B-reproducibility.sh"
```

### 4. Launch SFT

Set:
- `run.mode: sft`
- `run.run_id: <your-sft-run-id>`

Then run:

```bash
python tools/relayctl.py launch-stack configs/launch_stack.yaml
```

Check status:

```bash
python tools/relayctl.py status --commander-url http://127.0.0.1:8080
lium ps
lium exec <pod_name> 'tail -n 200 /tmp/relay-worker.log'
```

### 5. Launch RL

Reuse the same file, update:
- `run.mode: rl`
- `run.run_id: <your-rl-run-id>`
- optional: `run.save_rollout_trajectories: true`

Then run again:

```bash
python tools/relayctl.py launch-stack configs/launch_stack.yaml
```

### 6. Push latest checkpoint to Hugging Face (manual fallback)

If you want to push explicitly after run completion:

```bash
lium exec <pod_name> 'cd /workspace/slime/relay-trainer && /root/venv/bin/python tools/push_latest_to_hf.py --run-root /mnt/relay/runs/<run_id> --repo-id <hf_repo> --branch main'
```

### 7. LiveWeb-Arena quickstart configs

Use:
- `relay-trainer/configs/launch_stack.liveweb_sft.example.yaml`
- `relay-trainer/configs/launch_stack.liveweb_rl.example.yaml`

These are templates for HTTP-env-based workflows with LiveWeb-Arena.

## How to train from this repository

### Path A: direct slime wrappers (single entry)

```bash
# forwards to slime/train.py
python train.py --help

# forwards to slime/train_async.py
python train_async.py --help
```

Use this when you only need normal slime training and minimal orchestration.

### Path B: commander + worker orchestration

Use `relay-trainer/` when you need Lium pod orchestration, checkpoint lifecycle, and optional HF sync.

```bash
cd relay-trainer
python tools/relayctl.py launch-stack configs/launch_stack.example.yaml
```

For LiveWeb-Arena examples:
- `relay-trainer/configs/launch_stack.liveweb_sft.example.yaml`
- `relay-trainer/configs/launch_stack.liveweb_rl.example.yaml`

## Repository layout

```text
trainstack/
├── slime/                # Upstream framework (git submodule)
├── relay-trainer/        # Commander/Worker project
├── trainstack_plugins/   # Project-specific plugins (e.g. HTTP env adapter)
├── docs/                 # Documentation index + language-specific docs
├── scripts/              # Utility scripts / smoke tests
├── train.py              # Wrapper -> slime/train.py
└── train_async.py        # Wrapper -> slime/train_async.py
```

## Documentation map

Start here:
- `docs/README.md`

English:
- `docs/en/getting_started.md`
- `docs/en/training_quickstart.md`
- `docs/en/project_structure.md`

中文:
- `docs/zh/development_guide.md`
- `docs/zh/project_structure.md`
- `docs/zh/commander_worker_usage.md`
- `docs/zh/http_env_decoupling.md`
