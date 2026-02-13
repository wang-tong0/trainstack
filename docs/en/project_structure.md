# Project Structure

```text
trainstack/
├── slime/                      # Upstream framework, tracked as git submodule
├── relay-trainer/              # Commander/Worker orchestration project
│   ├── relay/
│   │   ├── commander_app.py    # Commander FastAPI service
│   │   ├── common/             # Schemas + HTTP client
│   │   └── worker/             # Worker loop, ckpt manager, HF sync
│   ├── docker/                 # Worker image build context
│   ├── trainer_blackbox/       # SFT/RL launcher scripts
│   ├── tools/relayctl.py       # Operations CLI
│   └── tests/                  # Unit/integration tests
├── trainstack_plugins/         # Project-specific plugin extensions
│   └── http_env/               # HTTP environment adapter/server examples
├── docs/                       # Documentation index and guides
├── scripts/                    # Utility scripts / smoke tests
├── train.py                    # Wrapper -> slime/train.py
└── train_async.py              # Wrapper -> slime/train_async.py
```

## Design intent

- Keep upstream `slime` isolated as a dependency.
- Put project logic in `relay-trainer/` and `trainstack_plugins/`.
- Prefer extension points and protocol decoupling over upstream patching.
