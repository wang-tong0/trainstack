# Getting Started

This guide explains how to bootstrap `trainstack` and choose the right training entrypoint.

## 1. Clone and initialize

```bash
git clone git@github.com:wang-tong0/trainstack.git
cd trainstack
git submodule update --init --recursive
```

## 2. Optional install

```bash
python -m pip install -e .
python -m pip install -e relay-trainer
```

## 3. Pick your workflow

### Workflow A: direct slime wrappers

Use when you want regular slime training with minimal orchestration.

```bash
python train.py --help
python train_async.py --help
```

### Workflow B: commander + worker orchestration

Use when you need pod orchestration, lease control, checkpoint lifecycle, and optional HF sync.

```bash
cd relay-trainer
python tools/relayctl.py launch-stack configs/launch_stack.example.yaml
```

LiveWeb-Arena examples:

- `relay-trainer/configs/launch_stack.liveweb_sft.example.yaml`
- `relay-trainer/configs/launch_stack.liveweb_rl.example.yaml`

## 4. Next reads

- `docs/en/training_quickstart.md`
- `docs/en/project_structure.md`
- `relay-trainer/README.md`
