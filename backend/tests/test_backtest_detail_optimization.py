"""回测详情端点优化测试"""
import tempfile
import os
from app.engine.storage import DataStorage


def test_get_backtest_result_by_id():
    """测试按 ID 直接查询回测结果"""
    with tempfile.TemporaryDirectory() as d:
        db = DataStorage(os.path.join(d, "test.db"))
        # 插入多条回测结果
        for i in range(5):
            db.save_backtest_result(
                summary={"avg_return_pct": i * 0.5, "avg_win_rate": 50 + i, "total_periods": 10 + i},
                details=[{"date": f"2024-01-{i+1:02d}", "end_date": f"2024-01-{i+6:02d}", "top_n": 20,
                          "avg_return_pct": i * 0.3, "win_rate": 50, "max_return": 2.0, "min_return": -1.0}],
                params={"startDate": "2024-01-01", "endDate": "2024-06-01", "topN": 20, "holdDays": 5},
            )

        # 按 ID 查询
        result = db.get_backtest_result(3)
        assert result is not None
        assert result["id"] == 3
        assert result["top_n"] == 20

        # 不存在的 ID
        result = db.get_backtest_result(999)
        assert result is None

        db.close()


def test_get_backtest_result_performance():
    """测试单条查询效率 vs 全量加载过滤"""
    with tempfile.TemporaryDirectory() as d:
        db = DataStorage(os.path.join(d, "test.db"))
        # 插入 100 条记录
        for i in range(100):
            db.save_backtest_result(
                summary={"avg_return_pct": 0.5, "avg_win_rate": 55, "total_periods": 20},
                details=[],
                params={"startDate": "2024-01-01", "endDate": "2024-06-01", "topN": 20, "holdDays": 5},
            )

        # 单条查询
        result = db.get_backtest_result(50)
        assert result is not None
        assert result["id"] == 50

        # 全量查询只返回分页数据
        results, total = db.get_backtest_results(limit=20, offset=0)
        assert total == 100
        assert len(results) == 20

        db.close()
