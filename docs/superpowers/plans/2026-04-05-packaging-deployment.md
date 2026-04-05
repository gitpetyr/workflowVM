# WorkflowVM 打包与部署实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 WorkflowVM 添加 pyproject.toml 现代打包、`workflowvm setup` CLI 一键初始化 runner repo、Docker 服务端部署、以及 release 触发 GHCR + PyPI 的 CI/CD workflow。

**Architecture:** 以 `pyproject.toml` + hatchling 为打包入口，将 server/sdk/agent 三个顶层目录打入 wheel；CLI 通过 `console_scripts` 注册，读取包内 `workflowvm/_resources/agent.yml` 并通过 GitHub API 初始化 runner repo；Docker 部署通过卷挂载 accounts.yml；CI/CD 在 release 发布时并行触发 GHCR push 和 PyPI upload。

**Tech Stack:** Python 3.12, hatchling, httpx (sync), importlib.resources, PyYAML, Docker, GitHub Actions (docker/login-action v3, docker/metadata-action v5, docker/build-push-action v5), twine

---

## 文件清单

| 操作 | 路径 | 用途 |
|------|------|------|
| 创建 | `pyproject.toml` | 现代打包配置，console_scripts 入口 |
| 创建 | `workflowvm/_resources/agent.yml` | 随包分发的 agent workflow 模板 |
| 创建 | `workflowvm/cli.py` | `workflowvm setup` 命令实现 |
| 创建 | `tests/test_cli.py` | CLI 单元测试 |
| 创建 | `Dockerfile` | 服务器容器镜像 |
| 创建 | `docker-compose.yml` | 本地/生产部署编排 |
| 创建 | `.github/workflows/docker.yml` | release 触发 GHCR push |
| 创建 | `.github/workflows/pypi.yml` | release 触发 PyPI 发布 |
| 修改 | `README.md` | 补充安装、setup CLI、Docker 用法 |

---

### Task 1: pyproject.toml 与包内资源

**Files:**
- Create: `pyproject.toml`
- Create: `workflowvm/_resources/agent.yml`

- [ ] **Step 1: 复制 agent.yml 到包内资源目录**

```bash
mkdir -p workflowvm/_resources
cp .github/workflows/agent.yml workflowvm/_resources/agent.yml
```

验证：
```bash
cat workflowvm/_resources/agent.yml | head -5
```
预期输出包含 `name: WorkflowVM Agent`

- [ ] **Step 2: 创建 pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "workflowvm"
version = "0.1.0"
description = "GitHub Actions Ubuntu runners as schedulable Python sandboxes"
readme = "README.md"
license = { text = "MIT" }
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

[tool.hatch.build.targets.wheel.force-include]
"workflowvm/_resources" = "workflowvm/_resources"
```

- [ ] **Step 3: 安装 hatchling 并验证构建**

```bash
/home/liveless/workspace/workflowVM/venv/bin/pip install hatchling build
/home/liveless/workspace/workflowVM/venv/bin/python -m build --wheel --no-isolation 2>&1 | tail -5
```

预期输出最后一行包含 `Successfully built workflowvm-0.1.0-py3-none-any.whl`

- [ ] **Step 4: 验证 wheel 包含所需文件**

```bash
/home/liveless/workspace/workflowVM/venv/bin/python -c "
import zipfile, glob
whl = glob.glob('dist/workflowvm-*.whl')[0]
with zipfile.ZipFile(whl) as z:
    names = z.namelist()
for n in sorted(names):
    if not n.endswith('.dist-info/'):
        print(n)
"
```

预期输出包含：
- `workflowvm/__init__.py`
- `workflowvm/_resources/agent.yml`
- `workflowvm/cli.py`（Task 2 完成后）
- `server/main.py`
- `sdk/controller.py`
- `agent/agent.py`

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml workflowvm/_resources/agent.yml
git commit -m "feat: add pyproject.toml and package resources"
```

---

### Task 2: workflowvm/cli.py（TDD）

**Files:**
- Create: `tests/test_cli.py`
- Create: `workflowvm/cli.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_cli.py`：

```python
import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from workflowvm.cli import (
    _create_repo,
    _github_headers,
    _push_workflow,
    _write_accounts_yml,
)


def test_github_headers():
    h = _github_headers("mytoken")
    assert h["Authorization"] == "Bearer mytoken"
    assert h["Accept"] == "application/vnd.github+json"
    assert h["X-GitHub-Api-Version"] == "2022-11-28"


def test_create_repo_already_exists():
    client = MagicMock()
    client.get.return_value = MagicMock(status_code=200)
    result = _create_repo(client, "tok", "owner", "repo")
    assert result is False
    client.post.assert_not_called()


def test_create_repo_creates_new():
    client = MagicMock()
    client.get.return_value = MagicMock(status_code=404)
    post_resp = MagicMock(status_code=201)
    post_resp.raise_for_status = MagicMock()
    client.post.return_value = post_resp

    result = _create_repo(client, "tok", "owner", "myrepo")
    assert result is True
    client.post.assert_called_once()
    body = client.post.call_args[1]["json"]
    assert body["name"] == "myrepo"
    assert body["auto_init"] is True


def test_push_workflow_new_file():
    client = MagicMock()
    client.get.return_value = MagicMock(status_code=404)
    put_resp = MagicMock()
    put_resp.raise_for_status = MagicMock()
    client.put.return_value = put_resp

    with patch("workflowvm.cli._load_agent_yml", return_value="agent-content"):
        _push_workflow(client, "tok", "owner", "repo")

    body = client.put.call_args[1]["json"]
    assert base64.b64decode(body["content"]).decode() == "agent-content"
    assert "sha" not in body
    assert body["message"] == "Add WorkflowVM agent workflow"


def test_push_workflow_existing_file():
    client = MagicMock()
    client.get.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"sha": "abc123"}),
    )
    put_resp = MagicMock()
    put_resp.raise_for_status = MagicMock()
    client.put.return_value = put_resp

    with patch("workflowvm.cli._load_agent_yml", return_value="content"):
        _push_workflow(client, "tok", "owner", "repo")

    body = client.put.call_args[1]["json"]
    assert body["sha"] == "abc123"


def test_write_accounts_yml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_accounts_yml("myuser/wvm-runner", "ghp_tok", "wss://example.com:8765", "secret")

    import yaml
    data = yaml.safe_load((tmp_path / "accounts.yml").read_text())
    assert data["accounts"][0]["runner_repo"] == "myuser/wvm-runner"
    assert data["accounts"][0]["token"] == "ghp_tok"
    assert data["server"]["api_token"] == "secret"
    assert data["server"]["port"] == 8765
    assert data["server"]["host"] == "0.0.0.0"


def test_write_accounts_yml_overwrite_denied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "accounts.yml").write_text("existing")
    monkeypatch.setattr("builtins.input", lambda _: "n")
    _write_accounts_yml("myuser/wvm-runner", "tok", "wss://x", "s")
    assert (tmp_path / "accounts.yml").read_text() == "existing"


def test_write_accounts_yml_overwrite_confirmed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "accounts.yml").write_text("existing")
    monkeypatch.setattr("builtins.input", lambda _: "y")
    _write_accounts_yml("myuser/wvm-runner", "tok", "wss://x", "s")
    import yaml
    data = yaml.safe_load((tmp_path / "accounts.yml").read_text())
    assert data["accounts"][0]["runner_repo"] == "myuser/wvm-runner"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/liveless/workspace/workflowVM && \
  venv/bin/pytest tests/test_cli.py -v 2>&1 | tail -10
```

预期：`ModuleNotFoundError: No module named 'workflowvm.cli'` 或全部 FAILED

- [ ] **Step 3: 实现 workflowvm/cli.py**

```python
"""workflowvm/cli.py - workflowvm setup command."""
import base64
import importlib.resources
import sys
from pathlib import Path

import httpx
import yaml


def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _load_agent_yml() -> str:
    return (
        importlib.resources.files("workflowvm")
        .joinpath("_resources/agent.yml")
        .read_text(encoding="utf-8")
    )


def _create_repo(client: httpx.Client, token: str, owner: str, repo: str) -> bool:
    """Check/create GitHub repo. Returns True if created, False if already exists."""
    r = client.get(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers=_github_headers(token),
    )
    if r.status_code == 200:
        return False
    r = client.post(
        "https://api.github.com/user/repos",
        headers=_github_headers(token),
        json={"name": repo, "private": False, "auto_init": True},
    )
    r.raise_for_status()
    return True


def _push_workflow(client: httpx.Client, token: str, owner: str, repo: str) -> None:
    """Push .github/workflows/agent.yml to the runner repo."""
    content = _load_agent_yml()
    encoded = base64.b64encode(content.encode("utf-8")).decode()
    path = ".github/workflows/agent.yml"
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

    r = client.get(url, headers=_github_headers(token))
    body: dict = {
        "message": "Add WorkflowVM agent workflow",
        "content": encoded,
    }
    if r.status_code == 200:
        body["sha"] = r.json()["sha"]

    r = client.put(url, headers=_github_headers(token), json=body)
    r.raise_for_status()


def _write_accounts_yml(
    repo: str, token: str, server_url: str, api_token: str
) -> None:
    """Write accounts.yml to the current directory."""
    path = Path("accounts.yml")
    if path.exists():
        ans = input("accounts.yml 已存在，覆盖？[y/N] ").strip().lower()
        if ans != "y":
            print("跳过生成 accounts.yml")
            return

    config = {
        "accounts": [
            {
                "username": repo.split("/")[0],
                "token": token,
                "runner_repo": repo,
                "max_concurrent": 5,
            }
        ],
        "server": {
            "host": "0.0.0.0",
            "port": 8765,
            "api_token": api_token,
        },
    }
    path.write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def main() -> None:
    print("WorkflowVM Setup")
    print("=" * 40)
    token = input("GitHub token (需要 repo + workflow scope): ").strip()
    repo = input("Runner repo (如 myuser/wvm-runner，不存在则自动创建): ").strip()
    server_url = input("Server WebSocket URL (用于 accounts.yml): ").strip()
    api_token = input("Server API token: ").strip()

    if "/" not in repo:
        print("错误：repo 格式应为 owner/name")
        sys.exit(1)

    owner, repo_name = repo.split("/", 1)

    with httpx.Client(timeout=30) as client:
        print(f"\n[1/3] 检查/创建 repo {repo} ...", end=" ", flush=True)
        created = _create_repo(client, token, owner, repo_name)
        print("✓ 已创建" if created else "✓ 已存在")

        print("[2/3] 推送 .github/workflows/agent.yml ...", end=" ", flush=True)
        _push_workflow(client, token, owner, repo_name)
        print("✓ 已推送")

    print("[3/3] 生成 accounts.yml ...", end=" ", flush=True)
    _write_accounts_yml(repo, token, server_url, api_token)
    print("✓ 已写入")

    print("\n完成！运行 `docker-compose up -d` 启动服务器。")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/liveless/workspace/workflowVM && \
  venv/bin/pytest tests/test_cli.py -v 2>&1 | tail -15
```

预期：`9 passed`

- [ ] **Step 5: 运行全量测试确认无回归**

```bash
cd /home/liveless/workspace/workflowVM && \
  venv/bin/pytest tests/ -v 2>&1 | tail -10
```

预期：全部通过（原有 34 个 + 新增 9 个 = 43 个）

- [ ] **Step 6: 提交**

```bash
git add workflowvm/cli.py tests/test_cli.py
git commit -m "feat: add workflowvm setup CLI"
```

---

### Task 3: Dockerfile + docker-compose.yml

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: 创建 Dockerfile**

```dockerfile
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ server/
COPY sdk/ sdk/
COPY agent/ agent/
COPY workflowvm/ workflowvm/

EXPOSE 8765

CMD ["python", "server/main.py", "--config", "/config/accounts.yml"]
```

- [ ] **Step 2: 创建 docker-compose.yml**

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

- [ ] **Step 3: 验证 Docker 构建成功**

```bash
cd /home/liveless/workspace/workflowVM && \
  docker build -t workflowvm-test . 2>&1 | tail -5
```

预期最后一行：`Successfully built <id>` 或 `=> => naming to docker.io/library/workflowvm-test`

- [ ] **Step 4: 提交**

```bash
git add Dockerfile docker-compose.yml
git commit -m "feat: add Dockerfile and docker-compose for server deployment"
```

---

### Task 4: CI/CD workflows

**Files:**
- Create: `.github/workflows/docker.yml`
- Create: `.github/workflows/pypi.yml`

- [ ] **Step 1: 创建 .github/workflows/docker.yml**

```yaml
name: Docker Build and Push to GHCR

on:
  release:
    types: [published]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract Docker metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=semver,pattern={{version}}
            type=raw,value=latest

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

- [ ] **Step 2: 创建 .github/workflows/pypi.yml**

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install build tools
        run: pip install build twine hatchling

      - name: Build package
        run: python -m build

      - name: Upload to PyPI
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
        run: twine upload dist/*
```

- [ ] **Step 3: 验证 workflow 文件语法**

```bash
python3 -c "
import yaml
for f in ['.github/workflows/docker.yml', '.github/workflows/pypi.yml']:
    yaml.safe_load(open(f))
    print(f'{f}: OK')
"
```

预期输出：
```
.github/workflows/docker.yml: OK
.github/workflows/pypi.yml: OK
```

- [ ] **Step 4: 提交**

```bash
git add .github/workflows/docker.yml .github/workflows/pypi.yml
git commit -m "feat: add CI/CD workflows for GHCR and PyPI on release"
```

---

### Task 5: 更新 README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 README.md 顶部安装部分后添加以下内容**

在 `## 快速开始` 章节开头插入安装说明，并在 `### 1. 配置账号池` 之前插入 setup CLI 说明：

将 README.md 的 `## 快速开始` 部分替换为：

```markdown
## 安装

```bash
pip install workflowvm
```

## 快速开始

### 1. 一键初始化 runner repo

```bash
workflowvm setup
```

交互式完成：创建 GitHub runner repo、推送 agent workflow、生成 `accounts.yml`。

所需 Classic PAT 权限（GitHub Settings → Developer settings → Personal access tokens）：
- `repo` - 完整仓库访问
- `workflow` - 触发 workflow_dispatch（必需）

### 2. 启动服务器（Docker）

```bash
docker-compose up -d
```

或使用发布的镜像：

```bash
docker pull ghcr.io/<your-org>/workflowvm:latest
GITHUB_REPOSITORY=<your-org>/workflowvm docker-compose up -d
```

### 3. 启动服务器（本地）

```bash
pip install workflowvm[server]
python -m server.main --config accounts.yml
```

### 4. 使用 SDK
```

- [ ] **Step 2: 删除原有 `### 1. 配置账号池` 和 `### 2. 在 runner repo 中提交 workflow 文件` 和 `### 3. 启动服务器` 三节，原 `### 4. 使用 SDK` 改为 `### 4. 使用 SDK`（保持不变）**

编辑后的 `## Classic PAT 权限` 章节已被合并到步骤 1 中，原独立章节可删除。

- [ ] **Step 3: 提交**

```bash
git add README.md
git commit -m "docs: update README with install, setup CLI, and Docker usage"
```

---

## 完成后

所有 Task 完成后，调用 `superpowers:finishing-a-development-branch` 技能完成开发分支处理。
