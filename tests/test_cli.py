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
        "    runner_repo: r\n"
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
        "    runner_repo: r\n"
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
