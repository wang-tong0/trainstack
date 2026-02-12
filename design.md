# Relay-Training on Lium for Affine (SFT + RL) — Implementation Design Doc (for Codex)

> **One-sentence summary**：用 **Lium 的容器 Pod + 可挂载 Volume** 作为不稳定 GPU 计算层，用一个极简的 **Commander（公网 CPU 小服务）** 做“租约 + 元数据仲裁”，在 **/mnt（Lium Volume）** 上做高频 checkpoint，实现 **接力式（Relay）训练**；低频把可复现的“里程碑”推到 **Hugging Face（L2）**，最后按 AffineFoundation 的工作流提交模型（HF repo + revision）。([docs.lium.io][1])

---

## 0. 背景与目标

### 0.1 背景

* 你希望在 Bittensor 生态内做模型训练与迭代，并在 `https://www.affine.io/`（Affine 子网相关生态）上刷榜。
* AffineFoundation 的开源实现给出了清晰的“拉取当前网络模型 → 改进（SFT/RL）→ 上传 HF → 部署/提交”的路径：

  * 从网络拉取模型 `af pull`
  * 训练改进后**手动上传**到 Hugging Face，并拿到 commit SHA
  * `af chutes_push` 部署并 `af commit` 上链提交([GitHub][2])
* 你的算力来自 Lium：以 **Pod（容器）** 方式提供 GPU，且支持通过 `lium` CLI 创建/管理 Pod、挂载 Volume、执行命令等。([docs.lium.io][3])
* Lium 的 **Volumes** 提供跨 Pod 的持久化存储，挂载到容器内的 `/mnt`。([docs.lium.io][4])
* Lium 还有平台级 Backups/Restores（压缩归档到云存储）能力，但其路径限制强调 **local volume mount（默认 `/root`）**，并提示不要用挂载在 `/mnt` 的外置卷做备份路径。([docs.lium.io][5])

  * 因此，本设计将 `/mnt` 作为 **高频 checkpoint 主存储（L1）**；L2 采用 Hugging Face（必选），Lium Backups 作为可选灾备（需要额外“复制到 /root”才能用）。

### 0.2 目标（必须达成）

1. **在不稳定 GPU Pod 上可持续训练**：Pod 随时可能中断/消失，但训练可以自动接力恢复。
2. **SFT + RL 都支持**：对训练框架保持“黑盒”，系统只负责生命周期与存储协议。
3. **极简、克制**：组件少、接口少、状态小，避免过度抽象。
4. **可落地**：明确到文件/目录/接口/脚本/运行命令层面，Codex 可按此直接实现。
5. **与 Lium 容器模式对齐**：训练工程必须封装为 Docker 镜像，并通过 Lium Template 运行。([docs.lium.io][6])

### 0.3 非目标（刻意不做）

* 不做多机分布式（跨 Pod 的 NCCL 集群编排）。
* 不做复杂调度系统（K8s/Argo/Ray 等）。
* 不实现完整训练框架（Slime/Megatron/sglang 等内部逻辑不侵入）。
* 不追求“完全自动提交上榜”（最后的 `af chutes_push/commit` 可先半自动，后续再自动化）。

---

## 1. 关键约束与事实（Lium / Affine）

### 1.1 Lium Pod / CLI 约束

* Pod 是容器环境；创建 Pod 用 `lium up`，可选择 template（Docker 镜像环境），并可用 `--volume` 挂载/创建 volume。([docs.lium.io][3])
* `lium templates` 可列出可用 Docker templates。([docs.lium.io][3])
* 可以 `lium ps / lium exec / lium ssh / lium rm` 管理 pod 生命周期与执行命令。([docs.lium.io][3])

### 1.2 Lium Volume 事实

* Volume 提供持久化存储，挂载路径 `/mnt`。([docs.lium.io][4])
* 同一 Volume **当前只能同时挂到一个 Pod**（FAQ）。([docs.lium.io][4])

  * 这与我们“同一时间只允许一个 Worker 写 L1”的锁设计一致。

### 1.3 Affine（Subnet 120）训练提交流程事实

* Affine 的官方 repo 明确：矿工需要从网络 pull 模型，改进后上传 HF，再部署到 Chutes 并 commit 上链。([GitHub][2])

---

## 2. 总体架构（最小可用）

### 2.1 组件

1. **Commander（公网 CPU，小服务）**

   * 单实例 FastAPI/Flask 均可（推荐 FastAPI）。
   * 职责：**租约锁（lease）**、**进度元数据记录**、**最近一次 HF 归档信息**。
   * 不传模型权重，只收发 JSON。
2. **Worker（Lium GPU Pod 内的容器）**

   * 你的训练镜像（包含：训练框架 + relay 守护逻辑 + hf 同步工具）。
   * 挂载 Lium Volume 到 `/mnt`（持久化 L1）。
   * 运行 `relay-entrypoint`：恢复 → 启动训练黑盒 → 监控 → 续租 → checkpoint 管理 →（低频）HF 同步。
3. **Hugging Face（L2）**

   * 归档“可复现里程碑”：`model`/`adapter`/`trainer_state`/`config`/`metrics`/`code_revision`。
   * 作为跨 Volume 损坏/误删/迁移的冷备与共享入口（并且 Affine 提交流程本来就要求 HF）。([GitHub][2])

> 可选：**Lium Backups** 作为额外灾备（但需要把关键文件复制到 `/root/...` 才满足其路径约束）。([docs.lium.io][5])

---

## 3. 存储分级与目录规范

### 3.1 L1（Volume /mnt）——强一致“训练现场”

* **挂载点**：`/mnt`（Lium Volume）。([docs.lium.io][4])
* **用途**：高频 checkpoint、optimizer state、rollout buffer（如需要）、训练日志、最近状态指针。

推荐目录（固定）：

```text
/mnt/relay/
├── runs/
│   └── <run_id>/                  # 一个训练 run 的工作区（支持多 run 并存，但一次只激活一个）
│       ├── data/                  # 可选：数据（尽量只放小索引/manifest，大数据用HF/对象存储另算）
│       ├── logs/                  # tb/wandb 本地缓存等
│       ├── ckpt/
│       │   ├── step_00001000/     # 实体 checkpoint（原子落盘）
│       │   ├── step_00002000/
│       │   ├── latest -> step_... # 软链接
│       │   └── _staging/          # 写入临时目录（原子 mv）
│       ├── hf/                    # HF 同步相关（last_synced.json 等）
│       └── state.json             # 本地状态：last_ok_step / last_ckpt_path / last_hf_rev
└── shared/
    ├── base_models/               # 可选：缓存基座模型（避免重复下载）
    └── wheelhouse/                # 可选：离线依赖缓存
```

### 3.2 L2（Hugging Face）——低频“里程碑归档”

* 归档粒度：**小时级 / 关键性能里程碑 / 每天**（由配置决定）。
* 归档内容：

  * 模型权重（全参或 adapter）
  * 训练状态（trainer_state、rng、tokenizer、config）
  * `metrics.jsonl`（关键指标）
  * `run_manifest.json`（run_id、git sha、数据版本、超参、affine基线uid等）

> 备注：如果你是全参 20GB+，HF 上传成本很高；因此 HF sync 必须是低频，并支持“只在里程碑/最优时上传”。

### 3.3 可选 L2b（Lium Backups）

* Lium Backups 会对你指定的路径做 zip 并上传云存储（带保留策略）。([docs.lium.io][5])
* 但其要求备份路径是 **local volume mount path（默认 `/root`）的子目录**，并明确不要用挂载在 `/mnt` 的外置卷。([docs.lium.io][5])
* 因此若启用：在每次“关键里程碑”后，把 `/mnt/relay/runs/<run_id>/state.json` + 一个“最小恢复包”(例如最近 checkpoint 的指针与校验信息，甚至压缩后的轻量权重) **复制到** `/root/relay_backup_export/<run_id>/...`，让 Lium Backups 去备它。

---

## 4. Commander 设计（HTTP 接口 + 状态机）

### 4.1 数据模型（最小字段）

* `active_lease`：

  * `run_id`
  * `lease_token`
  * `worker_id`
  * `expires_at`（服务器时间）
* `run_status[run_id]`：

  * `last_reported_step`
  * `last_ckpt`（路径/step）
  * `last_hf_repo` / `last_hf_revision`
  * `updated_at`
  * `status`：`RUNNING | PREEMPTED | FAILED | COMPLETED`

### 4.2 接口（保持 3 个，但补齐必要字段）

#### 1) `POST /api/lease/acquire`

**Request**

```json
{
  "worker_id": "lium-pod-xyz",
  "run_id": "affine-s120-20260209-a",
  "cap": { "gpu": "H200", "count": 8 }
}
```

**Logic**

* 若无 active lease 或 lease 已过期：发放新 lease。
* 若有 lease 且未过期：拒绝（除非 `force=true` 且具备管理员 token——可选）。

**Response**

```json
{
  "status": "granted",
  "lease_token": "uuid",
  "lease_expires_in_sec": 3600,
  "config": {
    "l1_root": "/mnt/relay",
    "run_id": "affine-s120-20260209-a",
    "ckpt_interval_sec": 600,
    "ckpt_keep_last_n": 3,
    "hf_sync_interval_sec": 14400,
    "hf_repo": "you/Affine-MyModel",
    "hf_push_on_improve": true
  }
}
```

#### 2) `POST /api/lease/renew`

```json
{ "lease_token": "uuid", "worker_id": "lium-pod-xyz" }
```

* 刷新 `expires_at`，返回 OK。

#### 3) `POST /api/job/report`

```json
{
  "lease_token": "uuid",
  "run_id": "affine-s120-20260209-a",
  "step": 50200,
  "latest_ckpt": "step_00050000",
  "hf": { "last_synced": true, "repo": "you/Affine-MyModel", "revision": "abc1234" },
  "status": "RUNNING",
  "msg": "optional short text"
}
```

> **注意**：Commander 记录仅用于观测与仲裁；真正的恢复依据仍以 L1 的 `latest` 与原子校验为准。

---

## 5. Worker（容器内）流程：启动、训练、恢复、归档

### 5.1 容器入口（entrypoint）职责

`relay-entrypoint` 做四件事：

1. **Acquire Lease**：拿到训练权。
2. **Recover**：从 L1 恢复；L1 不存在则从 HF 拉取（或从 `af pull` 拉取基线模型）。
3. **Run Black-box Trainer**：启动训练子进程（SFT 或 RL），并监控。
4. **Watchdog**：心跳续租、捕获 SIGTERM、维护 checkpoint、低频 HF sync。

### 5.2 恢复策略（严格优先级）

1. **L1 命中**：存在 `/mnt/relay/runs/<run_id>/ckpt/latest` 且校验通过 → `--resume_from` 指向该 checkpoint。
2. **L1 miss，HF 命中**：从 HF 下载最近一次归档 revision → 解压/落到 L1 → resume。
3. **都 miss**：执行基线初始化（两种二选一，按 run config）：

   * `af pull <uid>` 拉取当前网络模型作为基线（更贴近 affine 生态）。([GitHub][2])
   * 或从 HF 的 base model repo 拉取指定 revision。

### 5.3 Checkpoint 原子落盘规范（必须实现）

* 写入路径：`.../ckpt/_staging/step_xxx/`
* 写完后生成校验文件（例如 `sha256sums.txt` 或 `manifest.json`）
* `fsync`（能做就做）
* `mv _staging/step_xxx -> ckpt/step_xxx`
* `ln -sfn step_xxx ckpt/latest`
* 清理：保留最近 `N` 个 step 目录（默认 3），其余删除。

> 这是整个 Relay-Training 的核心：**只要 latest 始终指向一个完整目录，就能稳定恢复**。

### 5.4 SIGTERM / 抢占处理（Pod 消失前的最后机会）

* 捕获 SIGTERM：

  1. 立即写入 `state.json`（包含 last_ok_step、latest_ckpt）
  2. 尝试触发一次“轻量 checkpoint”（若训练框架支持快速保存）
  3. `report status=PREEMPTED`
* **不强制** HF sync：全参太大，不保证来得及；HF sync 由低频机制负责。

---

## 6. 与 Lium 平台对齐：镜像、Template、Volume、运行方式

### 6.1 镜像策略（必须）

你无法在 Pod 内“docker 再起 docker”来启动训练，因此训练工程必须 **直接封装为一个 Docker 镜像**，由 Lium template 指向该镜像启动。Lium 文档明确 template 定义了 **base Docker image / software stack / env settings**。([docs.lium.io][6])

**镜像必须包含：**

* 训练代码（Slime/Megatron/自研等）
* `relay-entrypoint` + watchdog
* HF 同步工具（huggingface_hub / git-lfs）
* （可选）`af` CLI（如果你要在 Worker 端直接 `af pull`）

### 6.2 Template 与创建 Pod

* 你可以用 `lium templates` 搜索/确认模板列表（也用于你后续验证自定义模板是否生效）。([docs.lium.io][3])
* 创建 Pod 用 `lium up`，并通过 `--volume` 附加或新建 volume：([docs.lium.io][3])

  * `--volume id:<HUID>`：挂已有卷
  * `--volume new:name=<NAME>`：创建并挂载新卷
* Volume 会挂载到容器 `/mnt`。([docs.lium.io][4])

**推荐实践：一个 run 绑定一个 volume**（或至少一个“活跃 run”绑定一个 volume），避免不同 run 的 checkpoint 相互污染。

### 6.3 运维方式（建议但不强制）

你可以把“外部控制面”放在本地或一台小 CPU 机：

* `lium ps` 查看 pod([docs.lium.io][3])
* `lium exec <pod> "<cmd>"` 执行命令/查看状态([docs.lium.io][3])
* `lium rm <pod>` 终止 pod（注意 volume 是否保留参数）([docs.lium.io][3])

---

## 7. 训练框架黑盒适配规范（Codex 需要实现的接口边界）

为了保持“框架无关”，我们只要求训练进程满足以下最小契约：

### 7.1 训练启动命令（由 run config 生成）

* SFT：`train_sft --data ... --out ... --resume_from ...`
* RL：`train_rl --env ... --out ... --resume_from ...`

**要求：**

* 支持指定输出目录（写 checkpoint 到 L1 的固定路径）
* 支持从某个 checkpoint 恢复（或由 wrapper 注入）

### 7.2 与 relay 系统的交互点（两种选一种）

**方案 A（推荐）：训练框架内回调保存 checkpoint**

* 训练框架负责每 N step 保存一次到指定目录；relay 只做“校验 + latest 指针 + 清理”。

**方案 B：relay 触发保存**

* relay 定时向训练进程发送信号（例如 `SIGUSR1`）触发保存（需要训练框架支持）。

> Codex 实施时优先做 A；B 只作为扩展点。

---

## 8. HF 归档（L2）策略（可控、低频、可复现）

### 8.1 触发条件（默认）

* 每 `hf_sync_interval_sec`（默认 4 小时）
* 或检测到“性能里程碑”：

  * `metrics.jsonl` 中某指标超过历史 best
  * 或 affine 评估脚本输出“dominates / improved”

### 8.2 归档方式（推荐实现顺序）

1. **snapshot 打包**：把 `ckpt/latest` 复制/硬链接到 `hf_snapshot/`（避免上传过程中 checkpoint 改动）。
2. **限速上传**：防止占满上行带宽（例如用 `huggingface_hub` 的分片上传 + 自己实现节流）。
3. 写入 `/mnt/relay/runs/<run_id>/hf/last_synced.json`
4. `job/report` 上报 `hf.revision`

---

## 9. Affine 上榜提交（对接点）

本系统的训练目标是产出一个 **HF repo + revision（commit SHA）**，以便执行：

* `af chutes_push --repo <user/repo> --revision <sha> ...`
* `af commit --repo <user/repo> --revision <sha> --chute-id ... --coldkey ... --hotkey ...`([GitHub][2])

**在本设计中：**

* Relay-Training 负责把里程碑推到 HF 并记录 revision。
* 提交动作可以先在外部控制面（你的本地/CPU 机）完成；后续再把它自动化进 Worker（不是第一阶段必做）。

---

## 10. 可观测性与故障处理

### 10.1 最小观测

* Worker 每 30–60 秒 `lease/renew`
* Worker 每 60–120 秒 `job/report`
* L1 写入：

  * `state.json`（last_ok_step / last_ckpt / last_hf）
  * `events.log`（简短事件：acquire、resume、ckpt_saved、hf_synced、sigterm）

### 10.2 常见故障与处理策略

1. **Pod 被回收/宕机**

   * 新 Pod 启动 → acquire lease → 从 `/mnt` 恢复 latest
2. **Volume 挂载失败**

   * 直接失败退出（不要继续训练），避免产生不可恢复的“无 L1”状态
3. **latest checkpoint 损坏**

   * 回退到上一个 step 目录（relay 在启动时扫描 `ckpt/step_*` 选择最新可用）
4. **HF 上传失败**

   * 不影响训练；记录失败原因，下次周期重试
5. **Commander 不可用**

   * Worker 进入“安全等待”：不启动训练（避免双写），每隔 backoff 重试 acquire

---

## 11. Codex 交付清单（按文件/模块拆分）

> 下面是 Codex 需要实现的“最小落地版本 (MVP)”清单。实现完即可在 Lium 上跑通接力式训练。

### 11.1 Repo 结构（建议）

```text
relay-trainer/
├── docker/
│   ├── Dockerfile
│   └── entrypoint.sh
├── relay/
│   ├── commander_app.py          # FastAPI app
│   ├── worker/
│   │   ├── relay_entry.py        # 主流程：lease/recover/run/watchdog
│   │   ├── ckpt.py               # 原子保存、扫描、清理
│   │   ├── hf_sync.py            # 低频归档
│   │   └── proc.py               # 子进程管理、信号处理
│   └── common/
│       ├── schema.py             # pydantic models
│       └── http.py               # requests client + retry/backoff
├── trainer_blackbox/
│   ├── launch_sft.sh             # 示例：如何启动你的训练框架
│   └── launch_rl.sh
├── configs/
│   └── run.yaml                  # run_id、hf_repo、interval等
└── README.md                     # 运维命令：lium up / volume / env vars
```

### 11.2 Dockerfile 要求（MVP）

* 基于合适 CUDA/PyTorch 镜像（与 Lium 节点匹配）
* 安装依赖（训练框架 + hf + 可选 af）
* `ENTRYPOINT ["bash", "docker/entrypoint.sh"]`

### 11.3 entrypoint.sh（MVP）

* 校验 `/mnt` 存在且可写（volume 已挂载）
* 导出环境变量（HF token / commander url / run_id）
* 执行：`python -m relay.worker.relay_entry`

### 11.4 Commander（MVP）

* SQLite/JSON 文件持久化即可（不需要数据库）
* 3 个接口 + 简单超时回收逻辑
* 基于 token 的简易鉴权（至少对 `/lease/acquire` 做 shared secret）

### 11.5 Worker（MVP）

* acquire → recover（L1优先）→ run blackbox → watchdog
* ckpt 原子目录 + latest 软链 + 保留 N 个
* hf_sync：按 interval 尝试上传（失败不影响训练）
* SIGTERM：写 state + report

---

## 12. 运行手册（面向实际操作）

### 12.1 一次性准备

1. 部署 Commander 到公网（任意 VPS / 轻量云函数都可）。
2. 构建并推送训练镜像到镜像仓库（GHCR/DockerHub）。
3. 在 Lium 创建/选择 template（指向你的镜像）。模板概念是 Lium Pod 环境的核心。([docs.lium.io][6])
4. 在 Lium 创建一个 volume（或在 `lium up` 时用 `--volume new:...` 创建）。([docs.lium.io][3])

### 12.2 启动 Pod（示例流程）

* 用 `lium ls` 找到合适节点，再 `lium up` 创建 pod，附加 volume。([docs.lium.io][3])
* Pod 起好后，用 `lium ps` 查看。([docs.lium.io][3])
* 如需调试，用 `lium ssh` / `lium exec` 进入容器。([docs.lium.io][3])

### 12.3 训练接力

* Pod 中训练中断 → 重新 `lium up` 起新 Pod，并挂同一个 volume → 自动从 `/mnt/relay/.../ckpt/latest` 恢复继续。

---

## 13. 设计取舍（为什么这样最简且鲁棒）

* **只依赖一个强持久层（/mnt volume）**：Lium volumes 的核心价值就是“pod 掉了数据还在”。([docs.lium.io][4])
* **Commander 不承载权重**：避免带宽与复杂性，且不成为吞吐瓶颈。
* **HF 归档低频**：符合全参大模型现实；并与 Affine 官方提交流程天然一致（HF repo + revision）。([GitHub][2])
* **锁与“单写者”假设成立**：Lium volume 也限制同一时间只能挂一个 pod，天然防止双写。([docs.lium.io][4])

---

### 附：下一步你可以让 Codex 直接开工的“最小实现顺序”

1. Commander（FastAPI）三接口 + 本地文件持久化
2. Worker：acquire/renew/report + L1 ckpt 扫描/latest/保留N
3. Worker：blackbox 子进程管理 + SIGTERM
4. HF sync（先做“手动触发一次上传”→再加 interval）
5. Dockerfile + entrypoint
6. Lium 上跑通：`lium up --template_id ... --volume ...` + 接力恢复验证

[1]: https://docs.lium.io/pods/overview "Overview | Lium"
[2]: https://github.com/AffineFoundation/affine?utm_source=chatgpt.com "GitHub - AffineFoundation/affine-cortex: Anima Machina"
[3]: https://docs.lium.io/cli/commands "Command Reference | Lium"
[4]: https://docs.lium.io/pods/volumes "Volumes | Lium"
[5]: https://docs.lium.io/pods/backups "Backups | Lium"
[6]: https://docs.lium.io/pods/create-pod "Create Pod | Lium"
