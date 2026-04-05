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
    repo_name = account["runner_repo"]
    runner_repo = f"{username}/{repo_name}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
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
                await asyncio.sleep(2)  # 等待 GitHub 完成 repo 初始化
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
    except httpx.RequestError as e:
        return SetupResult(username, runner_repo, "error", f"网络错误: {type(e).__name__}")


async def setup_all_accounts(accounts: list[dict]) -> list[SetupResult]:
    """并发对所有账号执行 setup_account。"""
    tasks = [setup_account(acc) for acc in accounts]
    return list(await asyncio.gather(*tasks))
