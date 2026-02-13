# Training Quick Start

This page gives practical start commands for common trainstack workflows.

## 1. Direct training via wrappers

The repository exposes two wrappers that forward to upstream slime:

- `train.py` -> `slime/train.py`
- `train_async.py` -> `slime/train_async.py`

Use:

```bash
python train.py --help
python train_async.py --help
```

## 2. Commander/Worker flow with relay-trainer

`relay-trainer` is the operational entrypoint for pod-based training.

```bash
cd relay-trainer
python tools/relayctl.py launch-stack configs/launch_stack.example.yaml
```

What this command does:

1. Starts local commander in background.
2. Calls `lium up` to create a worker pod.
3. Uploads worker run config to pod.
4. Starts worker process in pod background.

## 3. LiveWeb-Arena examples

For HTTP-decoupled environment integration, start from:

- SFT: `configs/launch_stack.liveweb_sft.example.yaml`
- RL: `configs/launch_stack.liveweb_rl.example.yaml`

Then:

```bash
cd relay-trainer
cp configs/launch_stack.liveweb_sft.example.yaml configs/launch_stack.yaml
# or use RL example
python tools/relayctl.py launch-stack configs/launch_stack.yaml
```

## 4. Verify run health

```bash
# commander
python tools/relayctl.py status --commander-url http://127.0.0.1:8080

# pods
lium ps

# worker log
lium exec <pod_name> 'tail -n 200 /tmp/relay-worker.log'
```

## 5. Detailed references

- `relay-trainer/README.md`
- `docs/zh/commander_worker_usage.md` (currently most detailed operations page)
