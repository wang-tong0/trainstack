# Commander / Worker 使用说明（详细）

本文给出 CPU 侧 commander 与 Lium worker 的完整启动流程。

## 1. 角色定义

- Commander（CPU 服务器）:
  - 提供 lease acquire/renew/report 接口
  - 持久化 run 状态
- Worker（Lium pod）:
  - 申请 lease
  - 执行 SFT/RL 训练
  - checkpoint 管理与恢复
  - 可选推送 Hugging Face

## 2. Commander 侧

### 2.1 启动

```bash
cd trainstack/relay-trainer
python -m pip install -e .
python tools/relayctl.py serve \
  --host 0.0.0.0 \
  --port 8080 \
  --state-path ./commander_state.json \
  --lease-seconds 3600 \
  --shared-secret '<SECRET>'
```

### 2.2 健康检查

```bash
python tools/relayctl.py status --commander-url http://127.0.0.1:8080
```

### 2.3 关键环境变量

- `RELAY_COMMANDER_STATE`: 状态文件路径
- `RELAY_LEASE_SECONDS`: 租约秒数
- `RELAY_SHARED_SECRET`: 鉴权密钥
- `RELAY_L1_ROOT`: 默认 `/mnt/relay`
- `RELAY_CKPT_INTERVAL`: 默认 600
- `RELAY_CKPT_KEEP_LAST_N`: 默认 3
- `RELAY_HF_SYNC_INTERVAL`: 默认 4 小时
- `RELAY_HF_REPO`: 默认 HF repo

## 3. Worker 侧（Lium pod）

### 3.1 启动前提

- 镜像已推送到 Docker Hub
- pod 挂载 volume 到 `/mnt`
- pod 可访问 commander（网络连通）

### 3.2 核心环境变量

Worker 可从配置文件或环境变量读取参数。环境变量优先。

- `COMMANDER_URL`
- `RUN_ID`
- `WORKER_ID`
- `MODE` (`sft` 或 `rl`)
- `HF_REPO`
- `HF_DRY_RUN` (`true`/`false`)
- `RELAY_SHARED_SECRET`
- `RELAY_RUN_CONFIG`（默认 `configs/run.yaml`）

### 3.3 最小 run.yaml

```yaml
commander_url: "http://<cpu-server>:8080"
run_id: "demo-run"
worker_id: "worker-001"
mode: "sft"
hf_repo: "<user>/<private_repo>"
hf_dry_run: true
relay_shared_secret: "<SECRET>"
```

### 3.4 Worker 启动流程

1. 调用 `/api/lease/acquire`。
2. 成功后创建运行目录: `/mnt/relay/runs/<run_id>/...`。
3. 检查已有 `ckpt`，若存在则自动恢复。
4. 按 `mode` 启动:
   - `trainer_blackbox/launch_sft.sh`
   - `trainer_blackbox/launch_rl.sh`
5. 定期 renew lease 与 report。
6. 训练完成后上报 `COMPLETED` 或 `FAILED`。

## 4. 对接真实 slime 训练

默认 `launch_*.sh` 使用 mock trainer。对接真实训练时设置:

```bash
export SLIME_SFT_CMD='bash /workspace/slime/slime/scripts/run-qwen3-4B-base-sft.sh'
export SLIME_RL_CMD='bash /workspace/slime/slime/scripts/run-qwen2.5-0.5B-reproducibility.sh'
```

Worker 会注入:

- `RELAY_OUTPUT_DIR`
- `RELAY_RESUME_FROM`

你可以在自定义训练脚本中读取这两个变量，映射 save/load 目录。

## 5. 在 Lium 上启动 pod（示例）

可先用 relayctl 生成命令模板:

```bash
python tools/relayctl.py print-lium-command \
  --template-id <template_id> \
  --pod-name relay-sft-01 \
  --volume id:<volume_huid> \
  --commander-url http://<cpu-server>:8080 \
  --run-id demo-run \
  --mode sft \
  --hf-repo <user>/<private_repo>
```

再按需要补充环境变量（密钥、dry-run 等）。

## 6. 状态与产物排查

运行目录:

```text
/mnt/relay/runs/<run_id>/
├── ckpt/
│   ├── step_00000001/
│   ├── step_00000002/
│   └── latest -> step_00000002
├── events.jsonl
├── state.json
└── hf/
    └── last_synced.json
```

排查顺序建议:

1. commander `/api/health`
2. worker 日志是否 acquire 成功
3. `/mnt/relay/runs/<run_id>/events.jsonl`
4. `state.json` 的 `status` / `latest_ckpt`
5. HF 推送记录 `hf/last_synced.json`

## 7. 常见故障

### 7.1 acquire 一直 denied

已有 active lease 未过期。检查 commander 状态文件，或在测试环境使用 `force=true` 的 acquire。

### 7.2 renew/report 返回 403

`lease_token` 或 `RELAY_SHARED_SECRET` 不一致。

### 7.3 不产生 checkpoint

训练脚本未写入 `RELAY_CKPT_STAGING_ROOT/step_*`。检查 `launch_*.sh` 与自定义训练命令。

### 7.4 HF 未上传

确认:

- `HF_REPO` 非空
- `HF_DRY_RUN=false`
- token 已在容器环境可用
