"""登录锁定用例的真实 pytest 脚本（qa-trace P4 演示库）。

用例的唯一真源是 ``cases/TC-LOGIN-003.yaml``；脚本侧只加 ``@pytest.mark.case``
标记，由 ``qa trace check`` 做双向对照（规范规则 9）。

这个演示故意让断言失败：产品当前在第 5 次失败后仍然返回 401 而不是 423，
所以 ``python -m qa_trace trace failure --run <run-id>`` 能把这次失败回溯到
``Case -> TestPoint -> Source``。修复产品后本脚本应自然转绿，不需要改用例。
"""

from __future__ import annotations

import pytest


class FakeAccount:
    """内存账号：模拟登录接口，让演示不依赖外部服务。"""

    def __init__(self, username: str = "qa01") -> None:
        self.username = username
        self.failed_attempts = 0
        self.locked = False

    def login(self, password: str) -> dict[str, object]:
        if self.locked:
            return {"status": 423, "message": "账号锁定 15 分钟"}
        if password == "Right@123":
            self.failed_attempts = 0
            return {"status": 200, "message": "登录成功"}
        self.failed_attempts += 1
        if self.failed_attempts >= 5:
            # 演示缺陷：这里本应把 locked 置为 True 并返回 423。
            return {"status": 401, "message": "用户名或密码错误"}
        return {
            "status": 401,
            "message": "用户名或密码错误",
            "remaining": 5 - self.failed_attempts,
        }


@pytest.mark.case("TC-LOGIN-003")
def test_lock_after_5_failures() -> None:
    account = FakeAccount()
    for _ in range(4):
        assert account.login("Wrong@123")["remaining"] == 5 - account.failed_attempts

    result = account.login("Wrong@123")
    assert result["status"] == 423, "第 5 次失败后应返回 423 并锁定账号"
    assert result["message"] == "账号锁定 15 分钟"
