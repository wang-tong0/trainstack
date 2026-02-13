# 项目结构说明

```text
trainstack/
├── slime/                      # 上游框架，git submodule（只读依赖）
├── relay-trainer/              # 训练编排与执行项目
│   ├── relay/
│   │   ├── commander_app.py    # Commander FastAPI 服务
│   │   ├── common/             # 通信模型与 HTTP 客户端
│   │   └── worker/             # Worker 主循环、ckpt 管理、HF 同步
│   ├── docker/                 # Worker 运行镜像
│   ├── trainer_blackbox/       # SFT/RL 启动脚本（可接真实 slime）
│   ├── tools/relayctl.py       # Commander 侧运维 CLI
│   └── tests/                  # Commander/Worker 测试
├── trainstack_plugins/         # trainstack 自定义扩展
│   └── http_env/               # HTTP 环境解耦样例插件
├── docs/zh/                    # 中文文档
├── scripts/http_env_smoke_test.sh
├── train.py                    # 转发到 slime/train.py
└── train_async.py              # 转发到 slime/train_async.py
```

## 目录职责

- `slime/`: 上游训练框架，按 submodule 管理版本。
- `relay-trainer/`: commander/worker 训练编排闭环。
- `trainstack_plugins/`: 与业务环境绑定的自定义能力。
- `docs/zh/`: 面向部署与开发的说明文档。

## 关键运行路径

1. Commander 在 CPU 机器启动，负责租约与状态管理。
2. Worker 在 Lium pod 内启动，向 commander 申请租约。
3. Worker 调用 `trainer_blackbox/launch_sft.sh` 或 `launch_rl.sh`。
4. 训练脚本在 staging 目录产出 checkpoint，worker 原子落盘到 `ckpt/step_xxx`。
5. Worker 定期 report，按策略同步到 Hugging Face。
