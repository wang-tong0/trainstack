# trainstack

`trainstack` 是一个训练编排仓库：在保持上游 `slime` 可升级、少侵入的前提下，承载项目级训练流程、插件扩展与部署运维能力。

英文 README：`README.md`

## 为什么需要这个仓库

实际项目通常需要：
- 接入自定义环境（例如 LiveWeb-Arena 这类 HTTP 环境），
- 在 Lium 上做 commander/worker 编排训练，
- 把镜像构建、运行脚本、运维说明与项目代码一起管理。

如果直接改上游 `slime`，后续升级成本会很高。  
`trainstack` 的目标就是把项目逻辑与上游核心解耦。

## 你可以在这里做什么

- 通过 wrapper 直接运行 slime 训练：
  - `python train.py ...`
  - `python train_async.py ...`
- 通过 `relay-trainer/` 运行 commander/worker 编排。
- 在 `trainstack_plugins/` 放置项目插件（例如 HTTP 环境适配器）。
- 用 HTTP 协议把环境与训练运行时解耦。

## 快速开始

```bash
git clone git@github.com:wang-tong0/trainstack.git
cd trainstack
git submodule update --init --recursive
```

可选安装：

```bash
python -m pip install -e .
python -m pip install -e relay-trainer
```

## 端到端快速上手（全新机器，Lium + HuggingFace）

本节目标：从 0 开始完成
1. 在 Lium 跑 SFT，
2. 在 Lium 跑 RL，
3. 将 checkpoint 同步到 HuggingFace。

### 1. 前置条件

- Python 3.10+、`git`
- 已安装并登录 Docker：
  [Docker 安装文档](https://docs.docker.com/get-started/get-docker/)，
  [docker login 文档](https://docs.docker.com/reference/cli/docker/login/)。
  可用以下命令验证：
  ```bash
  docker --version
  docker info | grep -i Username
  ```
- 已安装并初始化 Lium CLI：
  [Lium 文档](https://docs.lium.ai/)、
  [lium-cli (PyPI)](https://pypi.org/project/lium-cli/)。
  可用以下命令验证：
  ```bash
  lium --version
  test -f ~/.lium/config.ini && echo "lium config ok"
  ```
- 已配置 HuggingFace token：
  [HF token 页面](https://huggingface.co/settings/tokens)。
  可用以下命令验证：
  ```bash
  test -s ~/.cache/huggingface/token && echo "hf token cache ok"
  ```
- Lium 中已有指向 relay-trainer 镜像的模板。
  可用以下命令验证：
  ```bash
  lium templates relay-trainer
  ```
  输出中应能看到你期望的镜像与 tag（例如 `<dockerhub_user>/relay-trainer:<tag>`）。

### 2. 构建并推送训练镜像

```bash
cd trainstack
docker build -f relay-trainer/docker/Dockerfile -t <dockerhub_user>/relay-trainer:<tag> .
docker push <dockerhub_user>/relay-trainer:<tag>
```

然后把 Lium 模板的 image/tag 更新为该镜像。

### 3. 准备一键启动配置

```bash
cd relay-trainer
cp configs/launch_stack.example.yaml configs/launch_stack.yaml
```

编辑 `configs/launch_stack.yaml` 关键字段：

- `commander.public_url`：Lium pod 能访问到的 commander 地址
- `commander.shared_secret`：commander/worker 共享密钥
- `lium.template_id`：你的模板名/ID
- `lium.volume`：持久卷（`new:name=...` 或 `id:<huid>`）
- `run.hf_repo`：HF 模型仓库（如 `yourname/trainstack-demo`）
- `run.hf_dry_run`：真实上传时设为 `false`

若要跑真实训练（而不是 mock trainer），在 `worker.env` 里设置 slime 命令：

```yaml
worker:
  env:
    SLIME_SFT_CMD: "bash /workspace/slime/scripts/run-qwen3-4B-base-sft.sh"
    SLIME_RL_CMD: "bash /workspace/slime/scripts/run-qwen2.5-0.5B-reproducibility.sh"
```

### 4. 启动 SFT

设置：
- `run.mode: sft`
- `run.run_id: <你的-sft-run-id>`

执行：

```bash
python tools/relayctl.py launch-stack configs/launch_stack.yaml
```

检查：

```bash
python tools/relayctl.py status --commander-url http://127.0.0.1:8080
lium ps
lium exec <pod_name> 'tail -n 200 /tmp/relay-worker.log'
```

### 5. 启动 RL

复用同一个配置文件，修改：
- `run.mode: rl`
- `run.run_id: <你的-rl-run-id>`
- 可选：`run.save_rollout_trajectories: true`

再次执行：

```bash
python tools/relayctl.py launch-stack configs/launch_stack.yaml
```

### 6. 手动推送最新 checkpoint 到 HuggingFace（兜底）

如果希望在任务完成后手动触发上传：

```bash
lium exec <pod_name> 'cd /workspace/slime/relay-trainer && /root/venv/bin/python tools/push_latest_to_hf.py --run-root /mnt/relay/runs/<run_id> --repo-id <hf_repo> --branch main'
```

### 7. LiveWeb-Arena 快速配置

可直接使用：
- `relay-trainer/configs/launch_stack.liveweb_sft.example.yaml`
- `relay-trainer/configs/launch_stack.liveweb_rl.example.yaml`

这两份是基于 HTTP 环境解耦的 LiveWeb-Arena 模板。

## 如何在本仓库发起训练

### 路径 A：直接走 slime wrapper（单机入口）

```bash
# 转发到 slime/train.py
python train.py --help

# 转发到 slime/train_async.py
python train_async.py --help
```

适用场景：只需常规 slime 训练，不需要额外编排。

### 路径 B：commander + worker 编排训练

需要 Lium pod、checkpoint 生命周期管理、HF 同步等能力时，使用 `relay-trainer/`：

```bash
cd relay-trainer
python tools/relayctl.py launch-stack configs/launch_stack.example.yaml
```

LiveWeb-Arena 示例配置：
- `relay-trainer/configs/launch_stack.liveweb_sft.example.yaml`
- `relay-trainer/configs/launch_stack.liveweb_rl.example.yaml`

## 仓库结构

```text
trainstack/
├── slime/                # 上游框架（git submodule）
├── relay-trainer/        # Commander/Worker 训练编排项目
├── trainstack_plugins/   # 项目自定义插件（如 HTTP env adapter）
├── docs/                 # 文档索引与中英文文档
├── scripts/              # 工具脚本与 smoke 测试
├── train.py              # Wrapper -> slime/train.py
└── train_async.py        # Wrapper -> slime/train_async.py
```

## 文档导航

先看：
- `docs/README.md`

English:
- `docs/en/getting_started.md`
- `docs/en/training_quickstart.md`
- `docs/en/project_structure.md`

中文：
- `docs/zh/development_guide.md`
- `docs/zh/project_structure.md`
- `docs/zh/commander_worker_usage.md`
- `docs/zh/http_env_decoupling.md`
