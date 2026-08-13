"""AI Skill 参数 min/max 钳制测试 — 优化项 4 收尾。

锁定 registry.validate_params 对 int/float 数值参数的 min/max 校验行为
(超出范围静默钳制到边界), 防止后续回归。
"""
from __future__ import annotations

from app.ai_skills import registry


def _meta(params: list[dict]) -> dict:
    return {"id": "test_skill", "params": params}


_INT_P = {
    "key": "max_sectors", "label": "板块排名数量", "type": "int",
    "default": 5, "min": 1, "max": 20,
}
_FLOAT_P = {
    "key": "threshold", "label": "阈值", "type": "float",
    "default": 0.5, "min": 0.0, "max": 1.0,
}


def test_int_below_min_clamped_to_min():
    r = registry.validate_params(_meta([_INT_P]), {"max_sectors": -1})
    assert r["max_sectors"] == 1


def test_int_above_max_clamped_to_max():
    r = registry.validate_params(_meta([_INT_P]), {"max_sectors": 999})
    assert r["max_sectors"] == 20


def test_int_in_range_kept():
    r = registry.validate_params(_meta([_INT_P]), {"max_sectors": 5})
    assert r["max_sectors"] == 5


def test_float_below_min_clamped_to_min():
    r = registry.validate_params(_meta([_FLOAT_P]), {"threshold": -0.5})
    assert r["threshold"] == 0.0


def test_float_above_max_clamped_to_max():
    r = registry.validate_params(_meta([_FLOAT_P]), {"threshold": 3.0})
    assert r["threshold"] == 1.0


def test_missing_param_filled_with_default():
    r = registry.validate_params(_meta([_INT_P]), None)
    assert r["max_sectors"] == 5


def test_unknown_extra_param_kept():
    r = registry.validate_params(_meta([_INT_P]), {"unrelated": "x"})
    assert r["unrelated"] == "x"
