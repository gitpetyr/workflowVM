# WorkflowVM 打包与部署设计规格

## 概述

为 WorkflowVM 增加三项能力：
1. `workflowvm` CLI 可执行文件（含 `serve` 和 `setup` 子命令）
2. Docker 服务端部署（Dockerfile + docker-compose.yml）
3. CI/CD 自动发布（Release 触发 → 先推 PyPI 再构建推送 Docker 镜像到 GHCR）

## 一、包结构重组

### 目标结构

```
workflowvm/
  __init__.py              # 导出 Controller, RemoteObject（保持现有 API）
  cli/
    __init__.py
    main.py                # CLI 入口，dispatch subcommand（serve / setup）
    setup_cmd.py           # setup 子命令实现（避免与内置 setup 冲突）
  server/                  # 原 server/ 平移
    __init__.py
    account_pool.py
    github_api.py
    instance_pool.py
    remote_object.py
    session_manager.py
    main.py                # serve 逻辑，启动时调用 account_setup
    protocol.py
    account_setup.py       # 新增：账号可用性检查 + runner repo 初始化
  agent/                   # 原 agent/ 平移
    __init__.py
    agent.py
  sdk/                     # 原 sdk/ 平移
    __init__.py
    controller.py
    proxy.py

pyproject.toml             # 新增
Dockerfile                 # 新增
docker-compose.yml         # 新增
.github/workflows/
  agent.yml                # 已有，路径更新到 workflowvm/agent/agent.py
  release.yml              # 新增：自动发布 workflow
```

### Import 变更规则

所有模块内部 import 前缀统一替换：

| 原来 | 修改后 |
|------|--------|
| `from server.xxx import` | `from workflowvm.server.xxx import` |
| `from sdk.xxx import` | `from workflowvm.sdk.xxx import` |
| `from agent.xxx import` | `from workflowvm.agent.xxx import` |

`tests/` 目录同步更新。

### pyproject.toml 核心配置

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "workflowvm"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "websockets>=12.0",
    "httpx>=0.27.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "anyio>=4.0"]

[project.scripts]
workflowvm = "workflowvm.cli.main:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["workflowvm*"]
```

## 二、`workflowvm` CLI

### 子命令

```
workflowvm serve [--config accounts.yml]   # 启动服务器（默认子命令）
workflowvm setup [--config accounts.yml]   # 仅执行账号初始化，不启动服务器
```

### serve 启动流程

```
1. 加载 accounts.yml
2. 并发对每个账号执行 account_setup（见下）
3. 全部成功（或跳过已存在）后启动 WebSocket server
```

若任一账号 setup 失败（如 PAT 无效），打印警告但不阻止启动，该账号被标记为不可用。

### account_setup 逻辑（`workflowvm/server/account_setup.py`）

对单个账号执行：

1. `GET /user`（验证 PAT 有效性，确认用户名匹配）
2. `GET /repos/{owner}/{repo}`（检查 runner_repo 是否存在）
3. 若不存在：`POST /user/repos`（`private=true, auto_init=true`）
4. `GET /repos/{owner}/{repo}/contents/.github/workflows/agent.yml`（检查 workflow 文件）
5. 若不存在：`PUT` 创建文件（内容为 `workflowvm/agent/` 下的 `agent.yml` 模板 + `agent.py`）
6. 若已存在：跳过（幂等，不覆盖）

全程用 `httpx.AsyncClient`（已有依赖）。

### setup 子命令

与 serve 的账号初始化逻辑相同，执行完毕后打印每个账号的状态表格并退出。

```
账号           runner_repo              状态
user1          user1/wvm-runner         ✓ 已就绪
user2          user2/wvm-runner         ✓ 新建并推送 workflow
user3          user3/wvm-runner         ✗ PAT 无效（401）
```

## 三、Docker 部署

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
# 从 PyPI 安装（版本由构建时 ARG 注入）
ARG VERSION=latest
RUN pip install --no-cache-dir workflowvm==${VERSION}
EXPOSE 8765
ENTRYPOINT ["workflowvm"]
CMD ["serve", "--config", "/config/accounts.yml"]
```

### docker-compose.yml

```yaml
services:
  workflowvm:
    image: ghcr.io/OWNER/workflowvm:latest
    ports:
      - "8765:8765"
    volumes:
      - ./config:/config    # 用户将 accounts.yml 放入 ./config/
    restart: unless-stopped
```

用户部署步骤：
1. 创建 `./config/accounts.yml`（参考模板）
2. `docker compose up -d`

## 四、CI/CD 自动发布（`.github/workflows/release.yml`）

触发条件：`on: release: types: [published]`

### Job 1：publish-pypi

```
- checkout
- setup python 3.12
- pip install build
- python -m build
- pypa/gh-action-pypi-publish（需 secret: PYPI_API_TOKEN）
```

### Job 2：publish-docker

```
needs: publish-pypi         # 等 PyPI 发布成功
- checkout
- 登录 ghcr.io（docker/login-action，用 GITHUB_TOKEN）
- docker build \
    --build-arg VERSION=${{ github.ref_name }} \
    -t ghcr.io/${{ github.repository }}:${{ github.ref_name }} \
    -t ghcr.io/${{ github.repository }}:latest .
- docker push（两个 tag）
```

### 版本管理约定

- `pyproject.toml` 中的 `version` 字段需在发版前手动更新至与 Release tag 一致（如 `v0.1.0` → `version = "0.1.0"`）
- Release tag 格式：`v<major>.<minor>.<patch>`

## 五、agent.yml workflow 模板更新

原 `.github/workflows/agent.yml` 中的 agent 运行命令需更新：

```yaml
- name: Install agent dependencies
  run: pip install workflowvm   # 改为从 PyPI 安装完整包

- name: Start WorkflowVM Agent
  run: python -m workflowvm.agent.agent \
         --server "${{ inputs.server_url }}" \
         --token "${{ inputs.session_token }}" \
         --duration "${{ inputs.max_duration }}"
```

## 影响的现有文件

| 文件 | 变更类型 |
|------|---------|
| `server/*.py` | 移动 + import 前缀替换 |
| `agent/agent.py` | 移动 + import 前缀替换 |
| `sdk/*.py` | 移动 + import 前缀替换 |
| `workflowvm/__init__.py` | import 路径更新 |
| `tests/*.py` | import 路径更新 |
| `.github/workflows/agent.yml` | agent 安装方式 + 运行命令更新 |
| `README.md` | 启动命令更新为 `workflowvm serve` |
