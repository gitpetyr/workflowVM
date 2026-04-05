import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from workflowvm.server.github_api import GitHubAPI, WorkflowDispatchError

@pytest.mark.asyncio
async def test_dispatch_workflow_success():
    api = GitHubAPI(token="ghp_test")
    mock_response = MagicMock()
    mock_response.status_code = 204
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        MockClient.return_value = mock_client

        await api.dispatch_workflow(
            repo="user1/wvm-runner",
            server_url="wss://srv:8765",
            session_token="tok-abc",
            max_duration=300,
        )
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert "repos/user1/wvm-runner/actions/workflows/agent.yml/dispatches" in call_kwargs[0][0]
        body = call_kwargs[1]["json"]
        assert body["inputs"]["session_token"] == "tok-abc"
        assert body["inputs"]["max_duration"] == "300"

@pytest.mark.asyncio
async def test_dispatch_workflow_raises_on_error():
    api = GitHubAPI(token="ghp_test")
    mock_response = MagicMock()
    mock_response.status_code = 422
    mock_response.text = "Unprocessable Entity"
    mock_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
        "422", request=MagicMock(), response=mock_response
    ))

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        MockClient.return_value = mock_client

        with pytest.raises(WorkflowDispatchError):
            await api.dispatch_workflow(
                repo="user1/wvm-runner",
                server_url="wss://srv:8765",
                session_token="tok-abc",
                max_duration=300,
            )
