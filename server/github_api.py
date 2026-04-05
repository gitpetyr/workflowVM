import httpx


class WorkflowDispatchError(Exception):
    pass


class GitHubAPI:
    BASE = "https://api.github.com"

    def __init__(self, token: str):
        self._token = token

    async def dispatch_workflow(
        self,
        repo: str,
        server_url: str,
        session_token: str,
        max_duration: int = 300,
    ) -> None:
        """触发 workflow_dispatch，传递 agent 需要的参数。"""
        url = f"{self.BASE}/repos/{repo}/actions/workflows/agent.yml/dispatches"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        body = {
            "ref": "main",
            "inputs": {
                "server_url": server_url,
                "session_token": session_token,
                "max_duration": str(max_duration),
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=body)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise WorkflowDispatchError(
                    f"dispatch_workflow failed: {e.response.status_code} {e.response.text}"
                ) from e
