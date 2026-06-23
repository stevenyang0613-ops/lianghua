"""未上市新券过滤回归测试

问题背景:
- 模拟盘持仓中出现 118071 华峰转债、118070 南芯转债、113704 春风转债等
  price=100.0 的标的，实际这些是尚未上市的新券。
- EM bond_zh_cov 对未上市新券返回 债现价=100.0（发行价默认）。
- Sina bond_zh_hs_cov_spot 对未上市新券没有数据。
- JSL bond_cb_redeem_jsl 也返回 现价=100.0，转股起始日在未来。

旧过滤逻辑仅在 (sina<=0) and (jsl<=0) and em==100 时过滤，
但 JSL 对未上市新券也返回 100 > 0，所以未被过滤。

修复:
- 新增 _is_unlisted_new_bond 辅助方法，判定标准:
  - 上市时间缺失/无效/未来
  - 转股起始日缺失/无效/未来
  - 任一条件不满足即视为已上市/可交易
- redeem_map 保存 convert_start_date 字段
- _row_to_quote 在价格过滤后增加未上市新券判定
- EB 路径同样应用未上市过滤
"""
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from app.adapters.akshare import AKShareAdapter


class TestIsUnlistedNewBond:
    """测试 _is_unlisted_new_bond 辅助方法"""

    def setup_method(self):
        self.adapter = AKShareAdapter()

    def test_unlisted_when_list_date_is_nan_and_convert_start_is_future(self):
        """未上市新券: 上市时间NaT + 转股起始日在未来"""
        future_date = date.today() + timedelta(days=180)
        result = self.adapter._is_unlisted_new_bond(
            list_date=pd.NaT,
            convert_start_date=future_date,
        )
        assert result is True, "上市时间缺失且转股起始日在未来应判定为未上市"

    def test_unlisted_when_list_date_is_nan_and_convert_start_is_nan(self):
        """未上市新券: 上市时间NaT + 转股起始日NaT"""
        result = self.adapter._is_unlisted_new_bond(
            list_date=pd.NaT,
            convert_start_date=pd.NaT,
        )
        assert result is True, "上市时间和转股起始日均缺失应判定为未上市"

    def test_listed_when_list_date_is_past(self):
        """已上市: 上市时间是过去日期"""
        past_date = date.today() - timedelta(days=30)
        result = self.adapter._is_unlisted_new_bond(
            list_date=past_date,
            convert_start_date=None,
        )
        assert result is False, "上市时间为过去日期应判定为已上市"

    def test_listed_when_list_date_is_today(self):
        """今日上市: 上市时间等于今日"""
        today = date.today()
        result = self.adapter._is_unlisted_new_bond(
            list_date=today,
            convert_start_date=None,
        )
        assert result is False, "上市时间为今日应判定为已上市"

    def test_listed_when_convert_start_is_past_but_list_date_missing(self):
        """转股起始日已过: 即使上市时间缺失，也应视为已上市"""
        past_date = date.today() - timedelta(days=10)
        result = self.adapter._is_unlisted_new_bond(
            list_date=None,
            convert_start_date=past_date,
        )
        assert result is False, "转股起始日已过应判定为已上市"

    def test_unlisted_when_list_date_is_future(self):
        """未来才上市"""
        future_date = date.today() + timedelta(days=60)
        result = self.adapter._is_unlisted_new_bond(
            list_date=future_date,
            convert_start_date=None,
        )
        assert result is True, "上市时间在未来应判定为未上市"

    def test_unlisted_handles_string_dates(self):
        """字符串日期格式"""
        future_str = (date.today() + timedelta(days=180)).strftime("%Y-%m-%d")
        result = self.adapter._is_unlisted_new_bond(
            list_date=future_str,
            convert_start_date=future_str,
        )
        assert result is True

    def test_listed_handles_invalid_list_date_with_past_convert_start(self):
        """上市时间无效但转股起始日已过 → 已上市"""
        past_date = date.today() - timedelta(days=30)
        result = self.adapter._is_unlisted_new_bond(
            list_date="invalid_date",
            convert_start_date=past_date,
        )
        assert result is False

    def test_unlisted_handles_invalid_dates(self):
        """所有日期都无效 → 未上市"""
        result = self.adapter._is_unlisted_new_bond(
            list_date="invalid",
            convert_start_date="also_invalid",
        )
        assert result is True

    def test_unlisted_handles_nat_string(self):
        """NaT/None/空字符串 → 未上市"""
        for nat_value in ["NaT", "nan", "None", "", None, pd.NaT]:
            result = self.adapter._is_unlisted_new_bond(
                list_date=nat_value,
                convert_start_date=nat_value,
            )
            assert result is True, f"{nat_value!r} 应判定为未上市"


class TestRowToQuoteFiltersUnlisted:
    """测试 _row_to_quote 过滤未上市新券"""

    def setup_method(self):
        self.adapter = AKShareAdapter()

    def test_unlisted_bond_with_price_100_filtered_out(self):
        """未上市新券 (Sina空 + JSL=100 + EM=100) 应被过滤"""
        future_convert_start = date.today() + timedelta(days=180)
        row = pd.Series({
            "债券代码": "118071",
            "债券简称": "华峰转债",
            "申购日期": date.today(),
            "上市时间": pd.NaT,
            "正股代码": "688200",
            "正股价": 100.0,
            "转股价": 80.0,
            "转股价值": 125.0,
            "债现价": 100.0,
            "转股溢价率": -20.0,
        })
        # spot_map 空 → sina_price=0
        spot_map = {}
        # redeem_map 含 jsl_price=100 + convert_start_date=future
        from datetime import date as _date
        redeem_info = {
            "jsl_price": 100.0,
            "convert_start_date": future_convert_start,
            "maturity_date": future_convert_start.replace(year=future_convert_start.year + 6),
            "forced_call_days": 0,
            "is_called": False,
            "call_status": "",
        }
        result = self.adapter._row_to_quote(
            row, spot_map, {},
            redeem_info=redeem_info,
            rating="AA",
            stock_chg_map={}, stock_pe_map={}, stock_pb_map={},
            stock_turnover_map={}, fund_flow_map={},
        )
        assert result is None, "未上市新券 price=100 应被过滤返回 None"

    def test_listed_bond_with_price_100_kept(self):
        """已上市但暂未成交 (Sina空 + JSL=100 + EM=100) 应保留为 price=None"""
        past_convert_start = date.today() - timedelta(days=30)
        row = pd.Series({
            "债券代码": "118071",
            "债券简称": "华峰转债",
            "申购日期": date.today() - timedelta(days=60),
            "上市时间": date.today() - timedelta(days=30),
            "正股代码": "688200",
            "正股价": 100.0,
            "转股价": 80.0,
            "转股价值": 125.0,
            "债现价": 100.0,
            "转股溢价率": -20.0,
        })
        spot_map = {}
        redeem_info = {
            "jsl_price": 100.0,
            "convert_start_date": past_convert_start,
            "maturity_date": past_convert_start.replace(year=past_convert_start.year + 6),
            "forced_call_days": 0,
            "is_called": False,
            "call_status": "",
        }
        result = self.adapter._row_to_quote(
            row, spot_map, {},
            redeem_info=redeem_info,
            rating="AA",
            stock_chg_map={}, stock_pe_map={}, stock_pb_map={},
            stock_turnover_map={}, fund_flow_map={},
        )
        # 因为 上市时间存在 → 已上市，过滤逻辑通过；
        # 但 sina<=0 and jsl<=0 and em==100.0 条件不满足（jsl_price=100>0）
        # 所以应该返回 ConvertibleQuote, price=100
        # 但根据现有过滤，已有旧过滤 (sina<=0 and jsl<=0 and em==100) 不命中；
        # 未上市过滤因 list_date 有效而通过。
        # 最终应该返回有数据的 ConvertibleQuote，price=100
        assert result is not None, "已上市但价格=100 的债券应保留"
        assert result.price == 100.0

    def test_bond_with_real_sina_price_kept(self):
        """有真实 Sina 价格的债券正常保留"""
        recent_issue = date.today() - timedelta(days=365 * 2)
        row = pd.Series({
            "债券代码": "110081",
            "债券简称": "闻泰转债",
            "申购日期": recent_issue,
            "上市时间": recent_issue + timedelta(days=180),
            "正股代码": "600745",
            "正股价": 50.0,
            "转股价": 45.0,
            "转股价值": 111.11,
            "债现价": 115.5,
            "转股溢价率": 4.0,
        })
        spot_map = {"110081": {"price": 115.5, "change_pct": 1.5, "amount": 50000000.0}}
        redeem_info = {
            "jsl_price": 115.5,
            "convert_start_date": recent_issue + timedelta(days=180),
            "maturity_date": date.today() + timedelta(days=365 * 3),
            "forced_call_days": 0,
            "is_called": False,
            "call_status": "",
        }
        result = self.adapter._row_to_quote(
            row, spot_map, {},
            redeem_info=redeem_info,
            rating="AA+",
            stock_chg_map={}, stock_pe_map={}, stock_pb_map={},
            stock_turnover_map={}, fund_flow_map={},
        )
        assert result is not None
        assert result.price == 115.5
        assert result.code == "110081"