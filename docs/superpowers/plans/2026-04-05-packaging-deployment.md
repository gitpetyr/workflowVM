# WorkflowVM 打包与部署实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 WorkflowVM 增加 PyPI 打包、`workflowvm` CLI（含 serve/setup 子命令）、Docker 部署及 CI/CD 自动发布能力。

**Architecture:** 将 `server/`、`agent/`、`sdk/` 平移到 `workflowvm/` 子包，通过 `pyproject.toml` 发布为 `workflowvm` PyPI 包；CLI 入口 `workflowvm serve` 启动时自动检查/初始化 runner repo；Docker 镜像从 PyPI 安装包；Release 触发 CI/CD 先推 PyPI 再构建推送 GHCR 镜像。

**Tech Stack:** Python 3.12, setuptools, httpx, argparse, Docker, GitHub Actions

---

## 文件结构

| 文件 | 变更类型 | 职责 |
|------|---------|------|
| `pyproject.toml` | 新建 | 包元数据、依赖、entry_points |
| `workflowvm/server/` | 移动自 `server/` | 保持原有职责 |
| `workflowvm/agent/` | 移动自 `agent/` | 保持原有职责 |
| `workflowvm/sdk/` | 移动自 `sdk/` | 保持原有职责 |
| `workflowvm/cli/__init__.py` | 新建 | CLI 包标记 |
| `workflowvm/cli/main.py` | 新建 | argparse 入口，dispatch serve/setup |
| `workflowvm/cli/setup_cmd.py` | 新建 | setup 子命令：打印账号状态表格 |
| `workflowvm/server/account_setup.py` | 新建 | 验证 PAT、创建 repo、推送 workflow |
| `workflowvm/server/main.py` | 修改 | 启动时调用 account_setup |
| `tests/test_account_setup.py` | 新建 | account_setup 单元测试 |
| `tests/test_cli.py` | 新建 | CLI 子命令测试 |
| `tests/*.py` | 修改 | import 路径更新 |
| `.github/workflows/agent.yml` | 修改 | 改用 `pip install workflowvm` + entry point |
| `Dockerfile` | 新建 | 从 PyPI 安装，ENTRYPOINT workflowvm |
| `docker-compose.yml` | 新建 | 挂载 ./config:/config |
| `.github/workflows/release.yml` | 新建 | 自动发布 PyPI → GHCR |
| `README.md` | 修改 | 更新启动命令 |

---

### Task 1: 创建 pyproject.toml

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "workflowvm"
version = "0.1.0"
description = "GitHub Actions runner as a schedulable Python sandbox via WebSocket remote objects"
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
workflowvm-agent = "workflowvm.agent.agent:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["workflowvm*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: 验证 setuptools 可以找到包（此时 workflowvm/ 已存在）**

```bash
pip install -e ".[dev]" --quiet
python -c "import workflowvm; print('OK')"
```

Expected: 打印 `OK`，无报错。

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add pyproject.toml for PyPI packaging"
```

---

### Task 2: 包结构重组——移动文件

**Files:**
- Move: `server/` → `workflowvm/server/`
- Move: `agent/` → `workflowvm/agent/`
- Move: `sdk/` → `workflowvm/sdk/`
- Create: `workflowvm/cli/__init__.py`

- [ ] **Step 1: 用 git mv 保留历史，将三个模块迁移到 workflowvm/ 子目录**

```bash
git mv server workflowvm/server
git mv agent workflowvm/agent
git mv sdk workflowvm/sdk
mkdir -p workflowvm/cli
touch workflowvm/cli/__init__.py
```

- [ ] **Step 2: 验证目录结构**

```bash
find workflowvm -name "*.py" | sort
```

Expected 输出包含：
```
workflowvm/__init__.py
workflowvm/agent/__init__.py
workflowvm/agent/agent.py
workflowvm/cli/__init__.py
workflowvm/sdk/__init__.py
workflowvm/sdk/controller.py
workflowvm/sdk/proxy.py
workflowvm/server/__init__.py
workflowvm/server/account_pool.py
workflowvm/server/github_api.py
workflowvm/server/instance_pool.py
workflowvm/server/main.py
workflowvm/server/protocol.py
workflowvm/server/remote_object.py
workflowvm/server/session_manager.py
```

- [ ] **Step 3: Commit（此时 import 还未修改，测试会失败，这是预期的）**

```bash
git add workflowvm/ 
git commit -m "refactor: move server/agent/sdk into workflowvm package"
```

---

### Task 3: 更新所有模块的 import 路径

**Files:**
- Modify: `workflowvm/server/remote_object.py`
- Modify: `workflowvm/server/instance_pool.py`
- Modify: `workflowvm/server/main.py`
- Modify: `workflowvm/sdk/proxy.py`
- Modify: `workflowvm/sdk/controller.py`
- Modify: `workflowvm/__init__.py`
- Modify: `tests/test_account_pool.py`
- Modify: `tests/test_github_api.py`
- Modify: `tests/test_integration.py`
- Modify: `tests/test_protocol.py`
- Modify: `tests/test_proxy.py`
- Modify: `tests/test_remote_object.py`
- Modify: `tests/test_session_manager.py`

- [ ] **Step 1: 修改 workflowvm/server/remote_object.py 第 4 行 import**

将：
```python
from server.protocol import (
```
改为：
```python
from workflowvm.server.protocol import (
```

- [ ] **Step 2: 修改 workflowvm/server/instance_pool.py 第 3-6 行 import**

将：
```python
from server.account_pool import AccountPool, NoAccountAvailable
from server.github_api import GitHubAPI
from server.session_manager import SessionManager
from server.remote_object import RemoteObjectServer
```
改为：
```python
from workflowvm.server.account_pool import AccountPool, NoAccountAvailable
from workflowvm.server.github_api import GitHubAPI
from workflowvm.server.session_manager import SessionManager
from workflowvm.server.remote_object import RemoteObjectServer
```

- [ ] **Step 3: 修改 workflowvm/server/main.py 第 16-18 行 import**

将：
```python
from server.account_pool import AccountPool
from server.session_manager import SessionManager
from server.instance_pool import InstancePool
```
改为：
```python
from workflowvm.server.account_pool import AccountPool
from workflowvm.server.session_manager import SessionManager
from workflowvm.server.instance_pool import InstancePool
```

- [ ] **Step 4: 修改 workflowvm/sdk/proxy.py 第 2 行 import**

将：
```python
from server.protocol import RemoteRef
```
改为：
```python
from workflowvm.server.protocol import RemoteRef
```

- [ ] **Step 5: 修改 workflowvm/sdk/controller.py 的 import**

将：
```python
from sdk.proxy import RemoteObject, _run
from server.session_manager import SessionManager
from server.instance_pool import InstancePool, AcquireTimeout
```
改为：
```python
from workflowvm.sdk.proxy import RemoteObject, _run
from workflowvm.server.session_manager import SessionManager
from workflowvm.server.instance_pool import InstancePool, AcquireTimeout
```

并将文件中两处 lazy import：
```python
        from server.account_pool import AccountPool
        from server.session_manager import SessionManager
```
改为：
```python
        from workflowvm.server.account_pool import AccountPool
        from workflowvm.server.session_manager import SessionManager
```

- [ ] **Step 6: 修改 workflowvm/__init__.py**

将：
```python
from sdk.controller import Controller, RemoteVM
from sdk.proxy import RemoteObject
```
改为：
```python
from workflowvm.sdk.controller import Controller, RemoteVM
from workflowvm.sdk.proxy import RemoteObject
```

- [ ] **Step 7: 更新所有测试文件的 import**

`tests/test_account_pool.py` 第 5 行：
```python
from workflowvm.server.account_pool import AccountPool, NoAccountAvailable
```

`tests/test_github_api.py` 第 4 行：
```python
from workflowvm.server.github_api import GitHubAPI, WorkflowDispatchError
```

`tests/test_protocol.py` 第 2 行：
```python
from workflowvm.server.protocol import (
    encode_request, decode_response,
    OP_GETATTR, OP_CALL, OP_SETATTR, OP_GETITEM, OP_REPR, OP_DEL, OP_SHUTDOWN,
    RemoteRef, encode_value, decode_value,
    TYPE_REF, TYPE_VALUE, TYPE_ERROR,
)
```

`tests/test_proxy.py` 第 4-6 行：
```python
from workflowvm.server.protocol import RemoteRef
from workflowvm.sdk.proxy import RemoteObject
```

`tests/test_remote_object.py` 第 5-6 行：
```python
from workflowvm.server.remote_object import RemoteObjectServer, RemoteError
from workflowvm.server.protocol import RemoteRef
```

`tests/test_session_manager.py` 第 3 行：
```python
from workflowvm.server.session_manager import SessionManager, SessionNotFound, SessionTimeout
```

`tests/test_integration.py` 第 13-15 行：
```python
from workflowvm.server.session_manager import SessionManager
from workflowvm.server.remote_object import RemoteObjectServer
from workflowvm.sdk.proxy import RemoteObject
```

- [ ] **Step 8: 运行全部测试，验证重组后全部通过**

```bash
pytest tests/ -v
```

Expected: 所有已有测试通过，无 ImportError。

- [ ] **Step 9: Commit**

```bash
git add -u
git commit -m "refactor: update all imports to workflowvm.* namespace"
```

---

### Task 4: 实现 account_setup 模块（TDD）

**Files:**
- Create: `tests/test_account_setup.py`
- Create: `workflowvm/server/account_setup.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_account_setup.py`：

```python
import pytest
import base64
from unittest.mock import AsyncMock, MagicMock, patch
from workflowvm.server.account_setup import setup_account, setup_all_accounts, SetupResult

ACCOUNT = {
    "username": "user1",
    "token": "ghp_test",
    "runner_repo": "user1/wvm-runner",
    "max_concurrent": 5,
}


def _make_resp(status_code: int, json_data: dict = None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json = MagicMock(return_value=json_data or {})
    return resp


def _make_client(responses: list):
    """按顺序返回 responses 的 mock AsyncClient。"""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=responses[:])
    client.post = AsyncMock(return_value=_make_resp(201))
    client.put = AsyncMock(return_value=_make_resp(201))
    return client


@pytest.mark.asyncio
async def test_all_exists_returns_ready():
    """repo 已存在，workflow 已存在 → status=ready，不调用 POST/PUT。"""
    client = _make_client([
        _make_resp(200),  # GET /user
        _make_resp(200),  # GET /repos/user1/wvm-runner
        _make_resp(200),  # GET workflow file
    ])
    with patch("workflowvm.server.account_setup.httpx.AsyncClient", return_value=client):
        result = await setup_account(ACCOUNT)
    assert result.status == "ready"
    client.post.assert_not_called()
    client.put.assert_not_called()


@pytest.mark.asyncio
async def test_repo_missing_creates_repo_and_pushes_workflow():
    """repo 不存在 → POST 建 repo，PUT 推 workflow。"""
    client = _make_client([
        _make_resp(200),   # GET /user
        _make_resp(404),   # GET /repos → 不存在
        _make_resp(404),   # GET workflow → 不存在
    ])
    with patch("workflowvm.server.account_setup.httpx.AsyncClient", return_value=client):
        result = await setup_account(ACCOUNT)
    assert result.status == "created"
    client.post.assert_called_once()  # 建 repo
    client.put.assert_called_once()   # 推 workflow


@pytest.mark.asyncio
async def test_repo_exists_workflow_missing_pushes_workflow():
    """repo 已存在，workflow 不存在 → 只 PUT workflow。"""
    client = _make_client([
        _make_resp(200),  # GET /user
        _make_resp(200),  # GET /repos → 存在
        _make_resp(404),  # GET workflow → 不存在
    ])
    with patch("workflowvm.server.account_setup.httpx.AsyncClient", return_value=client):
        result = await setup_account(ACCOUNT)
    assert result.status == "workflow_added"
    client.post.assert_not_called()
    client.put.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_pat_returns_error():
    """PAT 无效（401）→ status=error，不继续后续步骤。"""
    client = _make_client([
        _make_resp(401),  # GET /user → 未授权
    ])
    with patch("workflowvm.server.account_setup.httpx.AsyncClient", return_value=client):
        result = await setup_account(ACCOUNT)
    assert result.status == "error"
    assert "401" in result.message


@pytest.mark.asyncio
async def test_setup_all_accounts_runs_concurrently():
    """setup_all_accounts 对多个账号都返回结果。"""
    accounts = [
        {**ACCOUNT, "username": "u1", "runner_repo": "u1/r"},
        {**ACCOUNT, "username": "u2", "runner_repo": "u2/r"},
    ]

    async def fake_setup(acc):
        return SetupResult(acc["username"], acc["runner_repo"], "ready", "OK")

    with patch("workflowvm.server.account_setup.setup_account", side_effect=fake_setup):
        results = await setup_all_accounts(accounts)

    assert len(results) == 2
    assert all(r.status == "ready" for r in results)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_account_setup.py -v
```

Expected: `ImportError: cannot import name 'setup_account'`

- [ ] **Step 3: 实现 workflowvm/server/account_setup.py**

```python
import asyncio
import base64
from dataclasses import dataclass

import httpx

_GITHUB_API = "https://api.github.com"

# agent.yml 模板，推送到 runner repo 的 .github/workflows/agent.yml
_AGENT_YML = """\
name: WorkflowVM Agent
on:
  workflow_dispatch:
    inputs:
      server_url:
        description: "WorkflowVM server WebSocket URL"
        required: true
      session_token:
        description: "Session token assigned by server"
        required: true
      max_duration:
        description: "Max runtime in seconds"
        required: false
        default: "300"

jobs:
  agent:
    runs-on: ubuntu-latest
    timeout-minutes: 360
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install WorkflowVM
        run: pip install workflowvm

      - name: Start WorkflowVM Agent
        run: |
          workflowvm-agent \\
            --server "${{ inputs.server_url }}" \\
            --token "${{ inputs.session_token }}" \\
            --duration "${{ inputs.max_duration }}"
"""


@dataclass
class SetupResult:
    username: str
    runner_repo: str
    status: str   # "ready" | "created" | "workflow_added" | "error"
    message: str


async def setup_account(account: dict) -> SetupResult:
    """
    对单个账号执行幂等初始化：
    1. 验证 PAT
    2. 检查/创建 runner_repo
    3. 检查/推送 .github/workflows/agent.yml
    """
    token = account["token"]
    username = account["username"]
    runner_repo = account["runner_repo"]
    _, repo_name = runner_repo.split("/", 1)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. 验证 PAT
        resp = await client.get(f"{_GITHUB_API}/user", headers=headers)
        if resp.status_code == 401:
            return SetupResult(username, runner_repo, "error", "PAT 无效 (401)")
        if resp.status_code != 200:
            return SetupResult(
                username, runner_repo, "error",
                f"GET /user 失败: {resp.status_code}"
            )

        # 2. 检查 runner_repo 是否存在
        repo_created = False
        resp = await client.get(f"{_GITHUB_API}/repos/{runner_repo}", headers=headers)
        if resp.status_code == 404:
            body = {"name": repo_name, "private": True, "auto_init": True}
            r2 = await client.post(f"{_GITHUB_API}/user/repos", headers=headers, json=body)
            if r2.status_code != 201:
                return SetupResult(
                    username, runner_repo, "error",
                    f"创建 repo 失败: {r2.status_code} {r2.text}"
                )
            repo_created = True
        elif resp.status_code != 200:
            return SetupResult(
                username, runner_repo, "error",
                f"GET /repos 失败: {resp.status_code}"
            )

        # 3. 检查/推送 workflow 文件
        workflow_path = ".github/workflows/agent.yml"
        resp = await client.get(
            f"{_GITHUB_API}/repos/{runner_repo}/contents/{workflow_path}",
            headers=headers,
        )
        if resp.status_code == 404:
            content_b64 = base64.b64encode(_AGENT_YML.encode()).decode()
            body = {
                "message": "Add WorkflowVM agent workflow",
                "content": content_b64,
            }
            r2 = await client.put(
                f"{_GITHUB_API}/repos/{runner_repo}/contents/{workflow_path}",
                headers=headers,
                json=body,
            )
            if r2.status_code != 201:
                return SetupResult(
                    username, runner_repo, "error",
                    f"推送 workflow 失败: {r2.status_code}"
                )
            if repo_created:
                return SetupResult(username, runner_repo, "created", "repo 已创建并推送 workflow")
            return SetupResult(username, runner_repo, "workflow_added", "已推送 workflow 文件")

        if resp.status_code == 200:
            return SetupResult(username, runner_repo, "ready", "已就绪")
        return SetupResult(
            username, runner_repo, "error",
            f"GET workflow 失败: {resp.status_code}"
        )


async def setup_all_accounts(accounts: list[dict]) -> list[SetupResult]:
    """并发对所有账号执行 setup_account。"""
    tasks = [setup_account(acc) for acc in accounts]
    return list(await asyncio.gather(*tasks))
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/test_account_setup.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_account_setup.py workflowvm/server/account_setup.py
git commit -m "feat: add account_setup module for runner repo initialization"
```

---

### Task 5: 实现 CLI（TDD）

**Files:**
- Create: `tests/test_cli.py`
- Create: `workflowvm/cli/main.py`
- Create: `workflowvm/cli/setup_cmd.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_cli.py`：

```python
import pytest
import sys
from unittest.mock import AsyncMock, patch, MagicMock
from workflowvm.server.account_setup import SetupResult


def _run_cli(*args):
    """辅助：用给定 argv 调用 CLI main()，返回退出码（None=成功）。"""
    from workflowvm.cli.main import main
    with patch("sys.argv", ["workflowvm", *args]):
        try:
            main()
            return 0
        except SystemExit as e:
            return e.code


def test_setup_subcommand_prints_results(tmp_path, capsys):
    """setup 子命令应调用 run_setup_sync 并打印结果。"""
    accounts_yml = tmp_path / "accounts.yml"
    accounts_yml.write_text(
        "accounts:\n"
        "  - username: u1\n"
        "    token: ghp_x\n"
        "    runner_repo: u1/r\n"
        "    max_concurrent: 1\n"
        "server:\n"
        "  host: 0.0.0.0\n"
        "  port: 8765\n"
        "  api_token: secret\n"
    )
    results = [SetupResult("u1", "u1/r", "ready", "已就绪")]

    with patch("workflowvm.cli.setup_cmd.setup_all_accounts", AsyncMock(return_value=results)):
        code = _run_cli("setup", "--config", str(accounts_yml))

    assert code == 0
    captured = capsys.readouterr()
    assert "u1" in captured.out


def test_setup_subcommand_exits_1_on_error(tmp_path, capsys):
    """setup 中有 error 账号时退出码为 1。"""
    accounts_yml = tmp_path / "accounts.yml"
    accounts_yml.write_text(
        "accounts:\n"
        "  - username: u1\n"
        "    token: bad\n"
        "    runner_repo: u1/r\n"
        "    max_concurrent: 1\n"
        "server:\n"
        "  host: 0.0.0.0\n"
        "  port: 8765\n"
        "  api_token: secret\n"
    )
    results = [SetupResult("u1", "u1/r", "error", "PAT 无效")]

    with patch("workflowvm.cli.setup_cmd.setup_all_accounts", AsyncMock(return_value=results)):
        code = _run_cli("setup", "--config", str(accounts_yml))

    assert code == 1


def test_unknown_command_exits_nonzero():
    """未知子命令应以非零退出。"""
    code = _run_cli("unknown-command")
    assert code != 0
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_cli.py -v
```

Expected: `ImportError: cannot import name 'main' from 'workflowvm.cli.main'`

- [ ] **Step 3: 实现 workflowvm/cli/setup_cmd.py**

```python
import asyncio
import sys

from workflowvm.server.account_pool import AccountPool
from workflowvm.server.account_setup import setup_all_accounts, SetupResult

_STATUS_ICON = {
    "ready": "✓",
    "created": "✓",
    "workflow_added": "✓",
    "error": "✗",
}


async def run_setup(config_path: str) -> list[SetupResult]:
    """加载 accounts.yml，对所有账号执行 setup，打印结果表格。"""
    pool = AccountPool(config_path)
    results = await setup_all_accounts(pool._accounts)
    print(f"{'账号':<20} {'runner_repo':<40} {'状态'}")
    print("-" * 72)
    for r in results:
        icon = _STATUS_ICON.get(r.status, "?")
        print(f"{icon} {r.username:<19} {r.runner_repo:<40} {r.message}")
    return results


def run_setup_sync(config_path: str) -> None:
    """同步入口：运行 setup，有 error 则以退出码 1 退出。"""
    results = asyncio.run(run_setup(config_path))
    errors = [r for r in results if r.status == "error"]
    if errors:
        sys.exit(1)
```

- [ ] **Step 4: 实现 workflowvm/cli/main.py**

```python
import argparse
import sys


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config", default="accounts.yml",
        help="Path to accounts.yml (default: accounts.yml)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="workflowvm",
        description="WorkflowVM server CLI",
    )
    sub = parser.add_subparsers(dest="command")

    serve_p = sub.add_parser("serve", help="Start the WorkflowVM server")
    _add_config_arg(serve_p)

    setup_p = sub.add_parser("setup", help="Check and initialize runner repos")
    _add_config_arg(setup_p)

    args = parser.parse_args()

    if args.command == "setup":
        from workflowvm.cli.setup_cmd import run_setup_sync
        run_setup_sync(args.config)

    elif args.command == "serve" or args.command is None:
        config = getattr(args, "config", "accounts.yml")
        import asyncio
        from workflowvm.server.main import main_async
        asyncio.run(main_async(config))

    else:
        parser.print_help()
        sys.exit(1)
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
pytest tests/test_cli.py -v
```

Expected: 3 passed.

- [ ] **Step 6: 运行全部测试确认无回归**

```bash
pytest tests/ -v
```

Expected: 全部通过。

- [ ] **Step 7: Commit**

```bash
git add workflowvm/cli/main.py workflowvm/cli/setup_cmd.py tests/test_cli.py
git commit -m "feat: add workflowvm CLI with serve and setup subcommands"
```

---

### Task 6: serve 启动时自动执行 account setup

**Files:**
- Modify: `workflowvm/server/main.py`

- [ ] **Step 1: 在 main_async 中调用 setup_all_accounts**

在 `workflowvm/server/main.py` 中，在 `account_pool = AccountPool(config_path)` 之后，`session_mgr = SessionManager(...)` 之前，插入以下代码：

```python
    from workflowvm.server.account_setup import setup_all_accounts
    log.info("检查并初始化所有 runner repo...")
    setup_results = await setup_all_accounts(account_pool._accounts)
    for r in setup_results:
        if r.status == "error":
            log.warning(f"账号 {r.username} ({r.runner_repo}) 初始化失败: {r.message}")
        else:
            log.info(f"账号 {r.username} ({r.runner_repo}): {r.message}")
```

完整修改后的 `main_async` 函数：

```python
async def main_async(config_path: str):
    global session_mgr, instance_pool, account_pool, _api_token

    account_pool = AccountPool(config_path)
    srv_cfg = account_pool.server_config
    host = srv_cfg.get("host", "0.0.0.0")
    port = int(srv_cfg.get("port", 8765))
    _api_token = srv_cfg.get("api_token", "")

    from workflowvm.server.account_setup import setup_all_accounts
    log.info("检查并初始化所有 runner repo...")
    setup_results = await setup_all_accounts(account_pool._accounts)
    for r in setup_results:
        if r.status == "error":
            log.warning(f"账号 {r.username} ({r.runner_repo}) 初始化失败: {r.message}")
        else:
            log.info(f"账号 {r.username} ({r.runner_repo}): {r.message}")

    session_mgr = SessionManager(reconnect_grace=60.0)

    ws_url = f"wss://{host}:{port}"
    instance_pool = InstancePool(
        account_pool=account_pool,
        session_manager=session_mgr,
        server_ws_url=ws_url,
    )

    stop = asyncio.Future()
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)
    loop.add_signal_handler(signal.SIGHUP, account_pool.reload_if_changed)

    cleanup_task = asyncio.create_task(periodic_cleanup())

    log.info(f"WorkflowVM server starting on {host}:{port}")
    async with serve(agent_handler, host, port):
        await stop

    cleanup_task.cancel()
    log.info("Server stopped.")
```

- [ ] **Step 2: 运行全部测试确认无回归**

```bash
pytest tests/ -v
```

Expected: 全部通过。

- [ ] **Step 3: Commit**

```bash
git add workflowvm/server/main.py
git commit -m "feat: auto-setup runner repos on server startup"
```

---

### Task 7: 更新 agent.yml workflow 模板

**Files:**
- Modify: `.github/workflows/agent.yml`

- [ ] **Step 1: 更新 .github/workflows/agent.yml**

将文件内容替换为：

```yaml
name: WorkflowVM Agent
on:
  workflow_dispatch:
    inputs:
      server_url:
        description: "WorkflowVM server WebSocket URL"
        required: true
      session_token:
        description: "Session token assigned by server"
        required: true
      max_duration:
        description: "Max runtime in seconds"
        required: false
        default: "300"

jobs:
  agent:
    runs-on: ubuntu-latest
    timeout-minutes: 360
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install WorkflowVM
        run: pip install workflowvm

      - name: Start WorkflowVM Agent
        run: |
          workflowvm-agent \
            --server "${{ inputs.server_url }}" \
            --token "${{ inputs.session_token }}" \
            --duration "${{ inputs.max_duration }}"
```

（注意：移除了 `actions/checkout@v4`，因为 agent 代码现在从 PyPI 安装，无需 checkout 仓库。）

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/agent.yml
git commit -m "feat: update agent.yml to install workflowvm from PyPI"
```

---

### Task 8: Dockerfile + docker-compose.yml

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: 创建 Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

ARG VERSION
RUN pip install --no-cache-dir "workflowvm==${VERSION}"

EXPOSE 8765

ENTRYPOINT ["workflowvm"]
CMD ["serve", "--config", "/config/accounts.yml"]
```

- [ ] **Step 2: 创建 docker-compose.yml**

```yaml
services:
  workflowvm:
    image: ghcr.io/OWNER/workflowvm:latest
    ports:
      - "8765:8765"
    volumes:
      - ./config:/config
    restart: unless-stopped
```

（用户部署时将 `OWNER` 替换为自己的 GitHub 用户名/组织，并在 `./config/accounts.yml` 中放置配置。）

- [ ] **Step 3: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "feat: add Dockerfile and docker-compose.yml for server deployment"
```

---

### Task 9: CI/CD 自动发布 workflow

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: 创建 .github/workflows/release.yml**

```yaml
name: Release

on:
  release:
    types: [published]

jobs:
  publish-pypi:
    name: Publish to PyPI
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install build
        run: pip install build

      - name: Build package
        run: python -m build

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          password: ${{ secrets.PYPI_API_TOKEN }}

  publish-docker:
    name: Publish Docker image to GHCR
    runs-on: ubuntu-latest
    needs: publish-pypi
    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract version tag
        id: version
        run: echo "tag=${GITHUB_REF_NAME#v}" >> $GITHUB_OUTPUT

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          build-args: |
            VERSION=${{ steps.version.outputs.tag }}
          tags: |
            ghcr.io/${{ github.repository }}:${{ steps.version.outputs.tag }}
            ghcr.io/${{ github.repository }}:latest
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add release workflow for PyPI and GHCR auto-publish"
```

---

### Task 10: 更新 README 并最终验证

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新 README.md 的快速开始部分**

将 `### 3. 启动服务器` 部分从：
```markdown
### 3. 启动服务器

\```bash
pip install -r requirements.txt
python server/main.py --config accounts.yml
\```
```

改为：
```markdown
### 3. 启动服务器

**方式 A：直接安装运行**

\```bash
pip install workflowvm
workflowvm serve --config accounts.yml
\```

**方式 B：Docker**

\```bash
mkdir config
cp accounts.yml config/
# 将 docker-compose.yml 中的 OWNER 替换为你的 GitHub 用户名
docker compose up -d
\```
```

并在 `### 2. 在 runner repo 中提交 workflow 文件` 部分改为：

```markdown
### 2. 初始化 runner repo（自动）

\```bash
workflowvm setup --config accounts.yml
\```

`setup` 命令会自动为 accounts.yml 中的每个账号创建 runner repo（若不存在）并推送 workflow 文件。`workflowvm serve` 启动时也会自动执行此初始化。
```

- [ ] **Step 2: 运行全部测试，最终确认**

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

Expected: 全部通过。

- [ ] **Step 3: 验证 CLI entry point 可用**

```bash
workflowvm --help
workflowvm-agent --help
```

Expected: 两个命令均显示帮助信息。

- [ ] **Step 4: 最终 commit**

```bash
git add README.md
git commit -m "docs: update README with new CLI commands and Docker deployment"
```
