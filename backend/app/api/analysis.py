import csv
import io
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import StreamingResponse
from app.engine.analysis import AnalysisEngine

router = APIRouter()

BOM = '﻿'


def _get_analysis_engine(request: Request) -> AnalysisEngine:
    """Get AnalysisEngine instance (cached) or create a no-cache fallback."""
    ae = getattr(request.app.state, "analysis_engine", None)
    if ae is not None:
        return ae
    return AnalysisEngine(cache_ttl=0)


def _validate_sort_order(sort_order: str) -> str:
    if sort_order not in ("asc", "desc"):
        return "asc"
    return sort_order

# CSV export column definitions per tab
CSV_COLUMNS = {
    "forced-redemption": [
        ("代码", "code"), ("名称", "name"), ("正股价", "stock_price"), ("转股价", "conversion_price"),
        ("占比", "ratio"), ("转股价值", "conversion_value"), ("溢价率", "premium_ratio"),
        ("触发天数", "trigger_days"), ("已计天数", "forced_call_days"), ("风险等级", "risk_level"),
        ("剩余年限", "remaining_years"), ("回售压力", "put_back_pressure"),
    ],
    "dual-low-ranking": [
        ("排名", "rank"), ("代码", "code"), ("名称", "name"), ("价格", "price"),
        ("溢价率", "premium_ratio"), ("双低值", "dual_low"), ("到期税后收益", "ytm"),
        ("成交量", "volume"), ("剩余年限", "remaining_years"), ("转股价值", "conversion_value"),
    ],
    "pulse-scan": [
        ("代码", "code"), ("名称", "name"), ("脉冲类型", "pulse_type"), ("涨跌幅", "change_pct"),
        ("价格", "price"), ("成交量", "volume"), ("放量倍数", "volume_ratio"),
        ("溢价率", "premium_ratio"), ("双低值", "dual_low"), ("剩余年限", "remaining_years"),
        ("严重程度", "severity"),
    ],
    "revision-probability": [
        ("代码", "code"), ("名称", "name"), ("正股价", "stock_price"), ("转股价", "conversion_price"),
        ("价差", "price_distance"), ("概率", "probability"), ("等级", "level"),
        ("溢价率", "premium_ratio"), ("剩余年限", "remaining_years"),
    ],
    "stock-correlation": [
        ("代码", "code"), ("名称", "name"), ("转债涨跌", "bond_change"), ("正股涨跌", "stock_change"),
        ("弹性系数", "elasticity"), ("关联度", "correlation"), ("相关系数", "pearson_correlation"),
        ("溢价率", "premium_ratio"), ("转股价值", "conversion_value"), ("价格", "price"), ("双低值", "dual_low"),
    ],
}


def _items_to_csv(items: list[dict], tab_key: str) -> StreamingResponse:
    columns = CSV_COLUMNS[tab_key]
    headers = [c[0] for c in columns]
    fields = [c[1] for c in columns]

    buf = io.StringIO()
    buf.write(BOM)
    writer = csv.writer(buf)
    writer.writerow(headers)
    for item in items:
        row = [item.get(f, "") for f in fields]
        writer.writerow(row)

    buf.seek(0)
    filename = f"{tab_key}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/forced-redemption")
async def get_forced_redemption(
    request: Request,
    limit: int = Query(default=0, ge=0),
    offset: int = Query(default=0, ge=0),
    min_volume: float = Query(default=0, ge=0),
    sort_by: str = Query(default=""),
    sort_order: str = Query(default="asc"),
):
    """强制赎回日历"""
    try:
        engine = request.app.state.engine
        ae = _get_analysis_engine(request)
        bonds = await engine.get_all_quotes()
        items = ae.cached_forced_redemption(bonds, limit=limit, offset=offset, min_volume=min_volume, sort_by=sort_by, sort_order=_validate_sort_order(sort_order))
        high_risk = [r for r in items if r["risk_level"] == "high"]
        return {
            "total": len(items),
            "total_unfiltered": len(bonds),
            "high_risk_count": len(high_risk),
            "items": items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dual-low-ranking")
async def get_dual_low_ranking(
    request: Request,
    limit: int = Query(default=0, ge=0),
    offset: int = Query(default=0, ge=0),
    min_volume: float = Query(default=0, ge=0),
    sort_by: str = Query(default=""),
    sort_order: str = Query(default="asc"),
):
    """双低排名"""
    try:
        engine = request.app.state.engine
        ae = _get_analysis_engine(request)
        bonds = await engine.get_all_quotes()
        items = ae.cached_dual_low_ranking(bonds, limit=limit, offset=offset, min_volume=min_volume, sort_by=sort_by, sort_order=_validate_sort_order(sort_order))
        return {"total": len(items), "total_unfiltered": len(bonds), "items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pulse-scan")
async def get_pulse_scan(
    request: Request,
    limit: int = Query(default=0, ge=0),
    offset: int = Query(default=0, ge=0),
    min_volume: float = Query(default=0, ge=0),
    sort_by: str = Query(default=""),
    sort_order: str = Query(default="asc"),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
):
    """脉冲扫描"""
    try:
        engine = request.app.state.engine
        ae = _get_analysis_engine(request)
        storage = getattr(request.app.state, "storage", None)
        bonds = await engine.get_all_quotes()
        items = ae.cached_scan_pulse(bonds, limit=limit, offset=offset, min_volume=min_volume, storage=storage, sort_by=sort_by, sort_order=_validate_sort_order(sort_order), start_date=start_date or None, end_date=end_date or None)
        high_severity = [r for r in items if r["severity"] == "high"]
        return {
            "total": len(items),
            "total_unfiltered": len(bonds),
            "high_severity_count": len(high_severity),
            "items": items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revision-probability")
async def get_revision_probability(
    request: Request,
    limit: int = Query(default=0, ge=0),
    offset: int = Query(default=0, ge=0),
    min_volume: float = Query(default=0, ge=0),
    sort_by: str = Query(default=""),
    sort_order: str = Query(default="asc"),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
):
    """下修概率评估"""
    try:
        engine = request.app.state.engine
        ae = _get_analysis_engine(request)
        storage = getattr(request.app.state, "storage", None)
        bonds = await engine.get_all_quotes()
        items = ae.cached_revision_probability(bonds, limit=limit, offset=offset, min_volume=min_volume, storage=storage, sort_by=sort_by, sort_order=_validate_sort_order(sort_order), start_date=start_date or None, end_date=end_date or None)
        high_prob = [r for r in items if r["level"] == "high"]
        return {
            "total": len(items),
            "total_unfiltered": len(bonds),
            "high_probability_count": len(high_prob),
            "items": items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock-correlation")
async def get_stock_correlation(
    request: Request,
    limit: int = Query(default=0, ge=0),
    offset: int = Query(default=0, ge=0),
    min_volume: float = Query(default=0, ge=0),
    sort_by: str = Query(default=""),
    sort_order: str = Query(default="asc"),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
):
    """正股关联分析"""
    try:
        engine = request.app.state.engine
        ae = _get_analysis_engine(request)
        storage = getattr(request.app.state, "storage", None)
        bonds = await engine.get_all_quotes()
        items = ae.cached_stock_correlation(bonds, limit=limit, offset=offset, min_volume=min_volume, storage=storage, sort_by=sort_by, sort_order=_validate_sort_order(sort_order), start_date=start_date or None, end_date=end_date or None)
        strong = [r for r in items if r["correlation"] == "强关联"]
        return {"total": len(items), "total_unfiltered": len(bonds), "strong_correlation_count": len(strong), "items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cache-stats")
async def get_cache_stats(request: Request):
    """缓存命中率统计"""
    try:
        ae = _get_analysis_engine(request)
        return ae.cache_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cache/clear")
async def clear_cache(request: Request):
    """清除所有缓存"""
    ae = _get_analysis_engine(request)
    cleared = ae.invalidate_all()
    return {"status": "ok", "cleared_entries": cleared}


@router.get("/forced-redemption/export")
async def export_forced_redemption(
    request: Request,
    min_volume: float = Query(default=0, ge=0),
    sort_by: str = Query(default=""),
    sort_order: str = Query(default="asc"),
):
    """导出强赎日历CSV"""
    try:
        engine = request.app.state.engine
        ae = _get_analysis_engine(request)
        bonds = await engine.get_all_quotes()
        items = ae.cached_forced_redemption(bonds, min_volume=min_volume, sort_by=sort_by, sort_order=_validate_sort_order(sort_order))
        return _items_to_csv(items, "forced-redemption")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dual-low-ranking/export")
async def export_dual_low_ranking(
    request: Request,
    min_volume: float = Query(default=0, ge=0),
    sort_by: str = Query(default=""),
    sort_order: str = Query(default="asc"),
):
    """导出双低排名CSV"""
    try:
        engine = request.app.state.engine
        ae = _get_analysis_engine(request)
        bonds = await engine.get_all_quotes()
        items = ae.cached_dual_low_ranking(bonds, min_volume=min_volume, sort_by=sort_by, sort_order=_validate_sort_order(sort_order))
        return _items_to_csv(items, "dual-low-ranking")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pulse-scan/export")
async def export_pulse_scan(
    request: Request,
    min_volume: float = Query(default=0, ge=0),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    sort_by: str = Query(default=""),
    sort_order: str = Query(default="asc"),
):
    """导出脉冲扫描CSV"""
    try:
        engine = request.app.state.engine
        ae = _get_analysis_engine(request)
        storage = getattr(request.app.state, "storage", None)
        bonds = await engine.get_all_quotes()
        items = ae.cached_scan_pulse(bonds, min_volume=min_volume, storage=storage, start_date=start_date or None, end_date=end_date or None, sort_by=sort_by, sort_order=_validate_sort_order(sort_order))
        return _items_to_csv(items, "pulse-scan")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revision-probability/export")
async def export_revision_probability(
    request: Request,
    min_volume: float = Query(default=0, ge=0),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    sort_by: str = Query(default=""),
    sort_order: str = Query(default="asc"),
):
    """导出下修概率CSV"""
    try:
        engine = request.app.state.engine
        ae = _get_analysis_engine(request)
        storage = getattr(request.app.state, "storage", None)
        bonds = await engine.get_all_quotes()
        items = ae.cached_revision_probability(bonds, min_volume=min_volume, storage=storage, start_date=start_date or None, end_date=end_date or None, sort_by=sort_by, sort_order=_validate_sort_order(sort_order))
        return _items_to_csv(items, "revision-probability")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock-correlation/export")
async def export_stock_correlation(
    request: Request,
    min_volume: float = Query(default=0, ge=0),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    sort_by: str = Query(default=""),
    sort_order: str = Query(default="asc"),
):
    """导出正股关联CSV"""
    try:
        engine = request.app.state.engine
        ae = _get_analysis_engine(request)
        storage = getattr(request.app.state, "storage", None)
        bonds = await engine.get_all_quotes()
        items = ae.cached_stock_correlation(bonds, min_volume=min_volume, storage=storage, start_date=start_date or None, end_date=end_date or None, sort_by=sort_by, sort_order=_validate_sort_order(sort_order))
        return _items_to_csv(items, "stock-correlation")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
