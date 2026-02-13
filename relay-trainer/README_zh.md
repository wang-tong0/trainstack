# relay-trainer（独立项目，slime 作为依赖）

本项目实现 `design.md` 中的 Relay-Training MVP：

- Commander（CPU 服务）：租约仲裁 + 运行元数据
- Worker（Lium pod 容器）：申请/续约/训练/看门狗/checkpoint/HF 同步
- Trainer blackbox 启动器：支持 `sft` 与 `rl`
- 面向 Lium 模板的 Docker 镜像
- CPU 侧 Python 工具：`tools/relayctl.py`

## 1. 目录结构

```text
relay-trainer/
├── configs/run.yaml
├── docker/
├── relay/
├── tests/
├── tools/relayctl.py
└── trainer_blackbox/
```

## 2. 本地 CPU 测试

```bash
cd relay-trainer
pip install -e '.[test]'
pytest -q
```

## 3. 启动 commander（CPU 侧）

```bash
cd relay-trainer
python tools/relayctl.py serve \
  --host 0.0.0.0 \
  --port 8080 \
  --state-path ./commander_state.json \
  --shared-secret '<SECRET>'
```

## 4. 构建并推送镜像

```bash
cd relay-trainer
docker build -t <dockerhub_user>/relay-trainer:0.1.0 -f docker/Dockerfile .
docker push <dockerhub_user>/relay-trainer:0.1.0
```

## 5. 在 Lium pod 运行

最小 `configs/run.yaml` 示例：

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

## 6. 对接真实 slime 的 SFT/RL 命令

默认 `launch_sft.sh` / `launch_rl.sh` 使用 mock trainer。  
接入真实训练时可设置：

```bash
export SLIME_SFT_CMD='bash /workspace/slime/scripts/run-qwen3-4B-base-sft.sh'
export SLIME_RL_CMD='bash /workspace/slime/scripts/run-qwen2.5-0.5B-reproducibility.sh'
```

## 7. commander 辅助命令

```bash
python tools/relayctl.py status --commander-url http://127.0.0.1:8080
```

## 8. 一键启动（commander + lium worker）

`launch-stack` 会完成：

- 本地后台启动 commander
- 调用 `lium up` 创建 pod
- 上传 worker 的 run 配置到 pod
- 在 pod 内后台启动 worker

```bash
cd /home/ubuntu/slime/relay-trainer
cp configs/launch_stack.example.yaml configs/launch_stack.yaml
python tools/relayctl.py launch-stack configs/launch_stack.yaml
```

### 8.1 YAML 字段说明（`launch_stack.yaml`）

顶层分组：
- `commander`：本地 commander 进程参数
- `lium`：pod 创建参数
- `run`：训练语义参数（`mode/run_id/hf` 等）
- `worker`：pod 内 worker 启动参数

`commander` 关键字段：
- `public_url`：pod 必须可访问（最关键）
- `shared_secret`：与 worker 保持一致
- `state_path/log_path/pid_path`：本地状态与日志

`lium` 关键字段：
- `template_id`：Lium 模板（必填）
- `volume`：建议使用持久卷
- `ttl`：自动释放时间

`run` 关键字段：
- `mode`：`sft` 或 `rl`
- `run_id`：运行 ID
- `hf_repo` / `hf_dry_run`
- `save_rollout_trajectories`（RL 轨迹缓存）

`worker` 关键字段：
- `remote_config_path`：上传到 pod 的 run 配置路径
- `remote_log_path` / `remote_pid_path`：worker 日志和 pid
- `command`：可覆盖默认 worker 启动命令
- `env`：注入给 worker 的环境变量

### 8.2 启动流程（建议）

1. 复制模板并修改 `commander.public_url` / `lium.template_id` / `lium.volume`。
2. 执行：
   ```bash
   python tools/relayctl.py launch-stack configs/launch_stack.yaml
   ```
3. 结果会输出 commander/pod/worker 的 JSON 摘要。

### 8.3 启动后验证

```bash
# commander
python tools/relayctl.py status --commander-url http://127.0.0.1:8080
tail -n 100 ./.relay-launch/commander.log

# pod / worker
lium ps
lium exec <pod_name> 'cat /tmp/relay-worker.pid && ps -p $(cat /tmp/relay-worker.pid) -o pid=,cmd='
lium exec <pod_name> 'tail -n 200 /tmp/relay-worker.log'
```

### 8.4 LiveWeb-Arena 示例（SFT / RL）

已提供两个可直接修改的示例：
- `configs/launch_stack.liveweb_sft.example.yaml`
- `configs/launch_stack.liveweb_rl.example.yaml`

使用方式：

```bash
cd /home/ubuntu/slime/relay-trainer
cp configs/launch_stack.liveweb_sft.example.yaml configs/launch_stack.yaml
# 或：
# cp configs/launch_stack.liveweb_rl.example.yaml configs/launch_stack.yaml
python tools/relayctl.py launch-stack configs/launch_stack.yaml
```

说明：
- 这两个示例假设你的运行环境可导入 `trainstack_plugins.http_env.*`，并可访问 `liveweb-arena`。
- `worker.env` 已包含：
  - `LIVEWEB_ARENA_ROOT`
  - `TRAINSTACK_HTTP_ENV_URL`
  - `TRAINSTACK_LLM_URL`
  - `PYTHONPATH`（slime + trainstack plugin + liveweb）
- 示例中的 `SLIME_SFT_CMD` / `SLIME_RL_CMD` 是模板占位，需替换为你的真实训练命令，并确保包含：
  - `--custom-generate-function-path trainstack_plugins.http_env.adapter.generate`
