from fastapi import APIRouter, Request, HTTPException
from app.engine.analysis import AnalysisEngine

router = APIRouter()


@router.get("/forced-redemption")
async def get_forced_redemption(request: Request):
    """强制赎回日历"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        results = AnalysisEngine.compute_forced_redemption(bonds)
        high_risk = [r for r in results if r["risk_level"] == "high"]
        return {
            "total": len(results),
            "high_risk_count": len(high_risk),
            "items": results,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dual-low-ranking")
async def get_dual_low_ranking(request: Request):
    """双低排名"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        results = AnalysisEngine.compute_dual_low_ranking(bonds)
        return {"total": len(results), "items": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pulse-scan")
async def get_pulse_scan(request: Request):
    """脉冲扫描"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        results = AnalysisEngine.scan_pulse(bonds)
        high_severity = [r for r in results if r["severity"] == "high"]
        return {
            "total": len(results),
            "high_severity_count": len(high_severity),
            "items": results,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revision-probability")
async def get_revision_probability(request: Request):
    """下修概率评估"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        results = AnalysisEngine.compute_revision_probability(bonds)
        high_prob = [r for r in results if r["level"] == "high"]
        return {
            "total": len(results),
            "high_probability_count": len(high_prob),
            "items": results,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock-correlation")
async def get_stock_correlation(request: Request):
    """正股关联分析"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        results = AnalysisEngine.compute_stock_correlation(bonds)
        return {"total": len(results), "items": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
