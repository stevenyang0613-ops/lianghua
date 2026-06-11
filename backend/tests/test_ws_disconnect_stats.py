"""WebSocket 断线原因统计测试"""
from app.api.ws import _ws_stats


def test_disconnect_reasons_structure():
    """测试断线原因统计结构"""
    assert "disconnect_reasons" in _ws_stats
    reasons = _ws_stats["disconnect_reasons"]
    expected_keys = {"client_close", "send_error", "receive_error",
                     "heartbeat_timeout", "auth_failed", "engine_unavailable",
                     "connection_limit", "unknown"}
    assert set(reasons.keys()) == expected_keys
    # 初始值都为0
    for key in expected_keys:
        assert isinstance(reasons[key], int)


def test_disconnect_reasons_increment():
    """测试断线原因可以递增"""
    from app.api.ws import _ws_stats
    original = _ws_stats["disconnect_reasons"]["client_close"]
    _ws_stats["disconnect_reasons"]["client_close"] += 1
    assert _ws_stats["disconnect_reasons"]["client_close"] == original + 1
    # 恢复原值
    _ws_stats["disconnect_reasons"]["client_close"] = original


def test_ws_stats_includes_all_fields():
    """测试 _ws_stats 包含所有统计字段"""
    required_fields = {
        "market_messages_sent", "market_bytes_sent",
        "signal_messages_sent", "signal_bytes_sent",
        "market_delta_messages", "market_full_messages",
        "disconnect_reasons",
    }
    assert required_fields.issubset(set(_ws_stats.keys()))
