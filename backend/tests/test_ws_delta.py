"""Tests for WebSocket delta computation with exclude_none optimization."""

import pytest
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.models.convertible import ConvertibleQuote
from app.api.ws import _build_tick_delta


class TestWsDelta:
    """Verify _build_tick_delta correctly handles exclude_none and field deletion."""

    def _make_bond(self, code: str, **kwargs) -> ConvertibleQuote:
        defaults = {"code": code, "name": "Test"}
        defaults.update(kwargs)
        return ConvertibleQuote(**defaults)

    def test_first_push_full_data(self):
        """首次推送应发送完整数据（不含 None 字段）。"""
        bond = self._make_bond("000001", price=100.0, pe=15.0)
        delta, snapshot = _build_tick_delta([bond], {})

        assert len(delta) == 1
        assert delta[0]["code"] == "000001"
        assert delta[0]["price"] == 100.0
        assert delta[0]["pe"] == 15.0
        assert "pb" not in delta[0], "None 字段不应出现在首次推送中"

    def test_delta_field_change(self):
        """字段变化应出现在 delta 中。"""
        bond1 = self._make_bond("000001", price=100.0)
        _, snapshot = _build_tick_delta([bond1], {})

        bond2 = self._make_bond("000001", price=105.0)
        delta, snapshot = _build_tick_delta([bond2], snapshot)

        assert len(delta) == 1
        assert delta[0]["price"] == 105.0
        assert "code" in delta[0]

    def test_delta_field_becomes_none(self):
        """字段从有值变为 None 时，delta 应发送 None 通知前端删除。"""
        bond1 = self._make_bond("000001", price=100.0, pe=15.0)
        _, snapshot = _build_tick_delta([bond1], {})

        bond2 = self._make_bond("000001", price=100.0, pe=None)
        delta, snapshot = _build_tick_delta([bond2], snapshot)

        # pe 从 15.0 变为 None（不在 model_dump 中），应被检测为变化
        assert len(delta) == 1
        # 由于 exclude_none=True，pe 不在 current 中，但 prev 中有
        # 修复后的 _build_tick_delta 遍历 set(current) | set(prev)，会检测到 pe 变化
        assert "pe" in delta[0], "字段从有值变为 None 应在 delta 中"
        assert delta[0]["pe"] is None

    def test_delta_field_appears_from_none(self):
        """字段从 None 变为有值时，delta 应发送新值。"""
        bond1 = self._make_bond("000001", price=100.0)
        _, snapshot = _build_tick_delta([bond1], {})

        bond2 = self._make_bond("000001", price=100.0, pe=15.0)
        delta, snapshot = _build_tick_delta([bond2], snapshot)

        assert len(delta) == 1
        assert "pe" in delta[0]
        assert delta[0]["pe"] == 15.0

    def test_no_change_no_delta(self):
        """字段无变化时，不应出现在 delta 中（timestamp 自动排除比较）。"""
        bond1 = self._make_bond("000001", price=100.0, pe=15.0)
        _, snapshot = _build_tick_delta([bond1], {})

        bond2 = self._make_bond("000001", price=100.0, pe=15.0)
        # timestamp 不同但代码已自动排除，不应产生 delta
        delta, snapshot = _build_tick_delta([bond2], snapshot)

        assert len(delta) == 0, "无变化时不应有 delta"

    def test_new_bond_full_data(self):
        """新增债券应发送完整数据。"""
        bond1 = self._make_bond("000001", price=100.0)
        _, snapshot = _build_tick_delta([bond1], {})

        bond2 = self._make_bond("000002", price=200.0, pe=20.0)
        delta, snapshot = _build_tick_delta([bond2], snapshot)

        # 新增债券，但 _build_tick_delta 只处理传入的 bonds 列表
        # 如果 bonds 列表只有 bond2，snapshot 中之前没有 000002，所以发送完整数据
        delta2, snapshot2 = _build_tick_delta([bond2], snapshot)
        # Wait, bond2 is already in snapshot now, so let's use a new bond
        bond3 = self._make_bond("000003", price=300.0)
        delta3, snapshot3 = _build_tick_delta([bond3], snapshot)

        assert len(delta3) == 1
        assert delta3[0]["code"] == "000003"
        assert delta3[0]["price"] == 300.0
