# Trainstack/Slime 解耦方案: 通过 HTTP 对接环境

目标: 不改 `slime/` 核心代码，仅通过 `--custom-generate-function-path` 接入外部环境服务。

## 目录

- 环境服务: `trainstack_plugins/http_env/server.py`
- 生成适配器: `trainstack_plugins/http_env/adapter.py`
- 本地 smoke: `scripts/http_env_smoke_test.sh`

## 交互协议

环境服务提供以下接口:

- `GET /health`
- `POST /v1/session/start`
- `POST /v1/session/step`
- `POST /v1/session/close`

`adapter.py` 在 rollout 中执行:

1. `start` 创建环境会话。
2. 把当前上下文发给 LLM 生成 action。
3. 用 `step` 把 action 发给环境并拿到 observation/reward/done。
4. 多轮循环直到 done 或长度上限。
5. 将结果填回 `Sample`:
   - `tokens`
   - `response`
   - `response_length`
   - `loss_mask` (`action=1`, `observation=0`)
   - `reward`
   - `status`
   - `rollout_log_probs`

## 运行方式

先设置环境变量:

```bash
export PYTHONPATH=$HOME/trainstack/slime:$HOME/trainstack:$PYTHONPATH
export TRAINSTACK_HTTP_ENV_URL=http://127.0.0.1:18080
# 可选: 让 adapter 不走 slime router，直接用一个 HTTP LLM 服务
export TRAINSTACK_LLM_URL=http://127.0.0.1:18081/generate
```

启动环境服务:

```bash
python -m trainstack_plugins.http_env.server
```

在 slime 训练命令中启用:

```bash
--custom-generate-function-path trainstack_plugins.http_env.adapter.generate
```

## 对接 liveweb-arena/其他环境

推荐做法:

1. 保持 `adapter.py` 不变，仅替换 `server.py` 的业务逻辑，或新建 `your_env_server.py`。
2. 让 `start/step/close` 保持同样 schema，这样训练侧无需改动。
3. 把环境依赖放在独立目录/镜像中，训练镜像只依赖 HTTP 协议。

这样后续升级 `slime` 时，只需回归测试 `custom-generate` 插件，不会和核心代码冲突。

## LiveWeb-Arena 首个自定义环境

已提供 `trainstack_plugins/http_env/liveweb_server.py` 作为 LiveWeb-Arena 适配服务。

快速验证:

```bash
scripts/liveweb_http_env_smoke_test.sh
```

该脚本会:

1. 启动 liveweb HTTP 环境服务（端口 `18082`）。
2. 启动 mock LLM（输出合法 stop 动作 JSON）。
3. 调用 `trainstack_plugins.http_env.adapter.generate` 跑完整闭环。
