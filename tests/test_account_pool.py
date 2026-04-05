import pytest
import os
import tempfile
import yaml
from workflowvm.server.account_pool import AccountPool, NoAccountAvailable

SAMPLE_CONFIG = {
    "accounts": [
        {"username": "u1", "token": "tok1", "runner_repo": "u1/r", "max_concurrent": 2},
        {"username": "u2", "token": "tok2", "runner_repo": "u2/r", "max_concurrent": 1},
    ],
    "server": {"host": "0.0.0.0", "port": 8765, "api_token": "secret"},
}

@pytest.fixture
def config_file(tmp_path):
    p = tmp_path / "accounts.yml"
    p.write_text(yaml.dump(SAMPLE_CONFIG))
    return str(p)

def test_pick_returns_account(config_file):
    pool = AccountPool(config_file)
    acc = pool.pick()
    assert acc["username"] in ("u1", "u2")
    assert "token" in acc
    assert "runner_repo" in acc

def test_pick_respects_max_concurrent(config_file):
    pool = AccountPool(config_file)
    # u2 最多1个并发，pick两次都优先 u1（最少使用）
    a1 = pool.pick()
    pool.release(a1["username"])
    a2 = pool.pick()
    assert a2 is not None

def test_pick_raises_when_all_full(config_file):
    pool = AccountPool(config_file)
    # u1 max=2, u2 max=1, 共3个槽
    pool.pick()
    pool.pick()
    pool.pick()
    with pytest.raises(NoAccountAvailable):
        pool.pick()

def test_release_decrements_count(config_file):
    pool = AccountPool(config_file)
    acc = pool.pick()
    pool.release(acc["username"])
    # 再次 pick 应该成功
    acc2 = pool.pick()
    assert acc2 is not None

def test_hot_reload(tmp_path):
    p = tmp_path / "accounts.yml"
    cfg = {
        "accounts": [{"username": "u1", "token": "t1", "runner_repo": "u1/r", "max_concurrent": 1}],
        "server": {"host": "0.0.0.0", "port": 8765, "api_token": "x"},
    }
    p.write_text(yaml.dump(cfg))
    pool = AccountPool(str(p))
    pool.pick()  # 占满

    # 写入新配置（增加账号）
    cfg["accounts"].append({"username": "u2", "token": "t2", "runner_repo": "u2/r", "max_concurrent": 1})
    import time; time.sleep(0.01)
    p.write_text(yaml.dump(cfg))
    pool.reload_if_changed()

    acc = pool.pick()  # 新账号可用
    assert acc["username"] == "u2"
