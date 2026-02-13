# Docker 镜像构建与发布

本文针对 `relay-trainer/docker/Dockerfile`。

## 1. 构建前准备

- 已登录 Docker Hub: `docker login`
- 本地包含完整仓库（含 submodule）:

```bash
git submodule update --init --recursive
```

注意: Dockerfile 使用 `COPY . /workspace/slime`，构建上下文必须是仓库根目录。

## 2. 构建命令

```bash
cd trainstack
docker build -f relay-trainer/docker/Dockerfile -t <dockerhub_user>/relay-trainer:<tag> .
```

建议 tag 规则:

- `<date>-<gitsha>`，例如 `20260212-a1b2c3d`
- 仅在回归通过后再更新 `latest`

## 3. 推送命令

```bash
docker push <dockerhub_user>/relay-trainer:<tag>
```

可选:

```bash
docker tag <dockerhub_user>/relay-trainer:<tag> <dockerhub_user>/relay-trainer:latest
docker push <dockerhub_user>/relay-trainer:latest
```

## 4. 镜像内容说明

镜像会安装:

- trainstack + relay-trainer（开发模式）
- slime（来自构建上下文中的 `slime/` submodule）
- sglang 运行时依赖

入口点:

- `relay-trainer/docker/entrypoint.sh`
- 默认执行: `python -m relay.worker.relay_entry --config ${RELAY_RUN_CONFIG:-configs/run.yaml}`

## 5. 常见问题

### 5.1 构建时找不到 slime

原因: submodule 未初始化。

修复:

```bash
git submodule update --init --recursive
```

### 5.2 容器启动时报 `/mnt missing`

原因: 未挂载 Lium volume。

修复: 在 pod 启动参数中挂载 volume 到 `/mnt`。

### 5.3 容器里不能 Docker in Docker 使用 GPU

这是当前已知限制。训练与推理进程应直接在 pod 主容器中运行，不要在容器内再起二级 docker。
