# Trainstack 开发文档

本文档描述 trainstack 的目标、开发边界、日常开发流程，以及与上游 slime 的协作方式。

## 1. 目标与边界

trainstack 是项目层编排仓库，负责:

- 承载项目自定义插件与脚本（例如 `trainstack_plugins/`）。
- 承载训练控制平面与运行时（`relay-trainer/`）。
- 通过 git submodule 引用上游 `slime/`，避免复制代码造成冲突。

trainstack 不负责:

- 修改上游 slime 核心逻辑。
- 在本仓库内维护 slime 的镜像副本。

## 2. 仓库初始化

```bash
git clone git@github.com:wang-tong0/trainstack.git
cd trainstack
git submodule update --init --recursive
```

可选: 安装 trainstack 自定义插件依赖。

```bash
python -m pip install -e .
```

可选: 安装 relay-trainer。

```bash
python -m pip install -e relay-trainer
```

## 3. 开发流程（推荐）

1. 拉取最新代码并更新 submodule。
2. 在 `trainstack_plugins/` 或 `relay-trainer/` 实现功能。
3. 本地执行最小验证。
4. 在 Lium pod 做真实验证。
5. 推镜像并记录 tag。

## 4. 最小验证命令

HTTP 解耦链路 smoke:

```bash
scripts/http_env_smoke_test.sh
```

relay-trainer 单元/集成测试:

```bash
cd relay-trainer
python -m pip install -e '.[test]'
pytest -q
```

## 5. 与上游 slime 协作原则

- 训练入口通过包装脚本转发到 `slime/train.py` 与 `slime/train_async.py`。
- 插件优先使用 slime 提供的扩展点（如 `--custom-generate-function-path`）。
- 若必须改动上游行为，优先在 trainstack 增加插件而非 patch slime 源码。
- 升级 slime 时，仅更新 submodule 指针并做回归验证。

## 6. 生产化建议

- commander 与 worker 使用共享密钥（`RELAY_SHARED_SECRET`）。
- 强制将 checkpoint 与状态写入挂载盘（例如 `/mnt/relay`）。
- HF 推送建议先 dry-run 再启用真实上传。
- 每次镜像发布使用不可变 tag（例如日期+git sha），避免 `latest` 漂移。
