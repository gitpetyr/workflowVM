import asyncio
import sys

from workflowvm.server.account_pool import AccountPool
from workflowvm.server.account_setup import setup_all_accounts, SetupResult

_STATUS_ICON = {
    "ready": "✓",
    "created": "✓",
    "workflow_added": "✓",
    "updated": "↑",
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
