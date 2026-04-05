# WorkflowVM 打包与部署设计规格

## 概述

为 WorkflowVM 增加三项能力：
1. **`workflowvm setup` CLI**：一键创建 GitHub runner repo 并推送 workflow 文件
2. **Docker 服务端部署**：Dockerfile + docker-compose.yml，挂载配置卷
3. **CI/CD 自动发布**：创建 GitHub Release 时同时推送 Docker 镜像到 GHCR 并发布 Python 包到 PyPI

## 一、包结构与 pyproject.toml

### 目录调整

```
workflowvm/
  __init__.py        # 重导出 Controller, RemoteVM, RemoteObject（现有）
  cli.py             # 新增：workflowvm setup 命令入口
  _resources/
    agent.yml        # 内嵌 agent workflow 文件（从 .github/workflows/ 复制）

server/              # 保持不变
sdk/                 # 保持不变
agent/               # 保持不变
Dockerfile           # 新增：服务器容器镜像
docker-compose.yml   # 新增：本地/生产部署编排
pyproject.toml       # 新增：现代 Python 打包配置
```

### pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "workflowvm"
version = "0.1.0"
description = "GitHub Actions Ubuntu runners as schedulable Python sandboxes"
requires-python = ">=3.12"
dependencies = [
    "websockets>=12.0",
    "httpx>=0.27.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
server = ["anyio>=4.0"]

[project.scripts]
workflowvm = "workflowvm.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["workflowvm", "server", "sdk", "agent"]

[tool.hatch.build.targets.wheel.sources]
"workflowvm/_resources" = "workflowvm/_resources"
```

`server`/`sdk`/`agent` 三个顶层目录均随 wheel 打包，用户 `pip install workflowvm` 后即可运行服务器和 CLI。

## 二、`workflowvm setup` CLI

### 功能

交互式初始化，完成三步操作：
1. 通过 GitHub API 检查/创建 runner repo（`POST /user/repos`）
2. 推送 `.github/workflows/agent.yml`（`PUT /repos/{owner}/{repo}/contents/...`），内容来自包内 `workflowvm/_resources/agent.yml`
3. 生成 `accounts.yml` 到当前目录

### 交互示例

```
$ workflowvm setup
GitHub token (需要 repo + workflow scope): ghp_xxx
Runner repo (如 myuser/wvm-runner，不存在则自动创建): myuser/wvm-runner
Server WebSocket URL (用于 accounts.yml): wss://example.com:8765
Server API token: your-secret-token

[1/3] 检查/创建 repo myuser/wvm-runner ...  ✓ 已创建
[2/3] 推送 .github/workflows/agent.yml ...  ✓ 已推送
[3/3] 生成 accounts.yml ...                ✓ 已写入

完成！运行 `docker-compose up -d` 启动服务器。
```

### 实现细节

- `workflowvm/cli.py` 中的 `main()` 函数，用 `input()` 收集参数
- 使用 `httpx` 同步客户端（无 asyncio），请求头包含 `Authorization: Bearer {token}`
- `agent.yml` 内容通过 `importlib.resources.files("workflowvm._resources").joinpath("agent.yml").read_text()` 读取
- `accounts.yml` 已存在时询问是否覆盖
- 任何 HTTP 错误（4xx/5xx）打印清晰错误信息并退出

## 三、Docker 部署

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ server/
COPY agent/ agent/
COPY workflowvm/ workflowvm/
COPY sdk/ sdk/
EXPOSE 8765
CMD ["python", "server/main.py", "--config", "/config/accounts.yml"]
```

### docker-compose.yml

```yaml
services:
  workflowvm-server:
    image: ghcr.io/${GITHUB_REPOSITORY:-workflowvm/workflowvm}:latest
    build: .
    ports:
      - "8765:8765"
    volumes:
      - ./accounts.yml:/config/accounts.yml:ro
    restart: unless-stopped
```

`accounts.yml` 通过卷挂载注入 `/config/accounts.yml`，不打入镜像，保持镜像内无敏感信息。

## 四、CI/CD — Release 触发

两个 workflow 均由 `on: release: types: [published]` 触发，并行执行。

### `.github/workflows/docker.yml`

步骤：
1. `actions/checkout@v4`
2. `docker/login-action` 登录 `ghcr.io`（使用 `secrets.GITHUB_TOKEN`，无需额外配置）
3. `docker/metadata-action` 生成标签：`latest` + `${{ github.ref_name }}`（如 `v0.1.0`）
4. `docker/build-push-action` 构建并推送到 `ghcr.io/${{ github.repository }}`

### `.github/workflows/pypi.yml`

步骤：
1. `actions/checkout@v4`
2. `actions/setup-python@v5`（Python 3.12）
3. `pip install build twine`
4. `python -m build`（生成 `dist/*.whl` 和 `dist/*.tar.gz`）
5. `twine upload dist/*`（使用 `secrets.PYPI_API_TOKEN`）

所需 Secret（用户在 repo Settings → Secrets and variables → Actions 中配置）：
- `PYPI_API_TOKEN`：PyPI API token，scope 限制为 `workflowvm` 项目

## 错误处理

| 场景 | 处理方式 |
|------|---------|
| setup: token 无效 | 打印 HTTP 401 错误，建议检查 token scope |
| setup: repo 已存在 | 跳过创建，直接推送 workflow 文件 |
| setup: accounts.yml 已存在 | 询问用户是否覆盖 |
| Docker build 失败 | CI workflow 失败，不推送镜像 |
| PyPI 上传失败 | CI workflow 失败，版本不冲突时可重新触发 |

## 测试范围

- `workflowvm/cli.py`：用 `unittest.mock` mock `httpx.Client`，验证 API 调用序列和 accounts.yml 生成内容
- Dockerfile：CI 中 `docker build` 验证构建成功
- CI workflows：通过创建 GitHub Release 手动验证端到端流程
