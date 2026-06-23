"""模拟盘 REST API - 每个策略独立账户，自动执行信号"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter()


def _get_manager(request: Request):
    manager = getattr(request.app.state, "paper_trade_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="模拟盘管理器未初始化")
    return manager


class CreateAccountRequest(BaseModel):
    strategy_id: str = Field(min_length=1)
    initial_cash: float = Field(default=100_000_000.0, gt=0)
    params: Optional[dict] = None


class UpdateParamsRequest(BaseModel):
    params: dict = Field(default_factory=dict)


@router.get("/accounts")
async def list_accounts(request: Request):
    """列出所有模拟盘账户及刷新状态
    
    Returns:
        accounts: 账户列表，每个账户包含 id/strategy_id/strategy_name/is_running/initial_cash/cash/positions 等
        refresh_fail_count: 连续刷新失败次数（>=5 触发前端警告）
        refresh_total_fails: 全局累计刷新失败次数（>=threshold 触发前端严重警告）
        refresh_total_fail_threshold: 全局失败阈值，前端据此决定警告级别
    """
    manager = _get_manager(request)
    return {
        "accounts": manager.list_accounts(),
        "refresh_fail_count": manager._refresh_fail_count,
        "refresh_total_fails": manager._refresh_total_fails,
        "refresh_total_fail_threshold": manager._refresh_total_fail_threshold,
    }


@router.post("/accounts")
async def create_account(req: CreateAccountRequest, request: Request):
    manager = _get_manager(request)
    try:
        account = manager.create_account(
            strategy_id=req.strategy_id,
            initial_cash=req.initial_cash,
            params=req.params,
        )
        return account.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/accounts/{account_id}")
async def get_account(account_id: str, request: Request):
    manager = _get_manager(request)
    try:
        return manager.get_account(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="账户不存在")


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: str, request: Request):
    manager = _get_manager(request)
    try:
        manager.delete_account(account_id)
        return {"status": "ok"}
    except KeyError:
        raise HTTPException(status_code=404, detail="账户不存在")


@router.post("/accounts/{account_id}/start")
async def start_account(account_id: str, request: Request):
    manager = _get_manager(request)
    try:
        manager.start_account(account_id)
        return manager.get_account(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="账户不存在")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/accounts/{account_id}/stop")
async def stop_account(account_id: str, request: Request):
    manager = _get_manager(request)
    try:
        manager.stop_account(account_id)
        return manager.get_account(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="账户不存在")


@router.post("/accounts/{account_id}/reset")
async def reset_account(account_id: str, request: Request):
    manager = _get_manager(request)
    try:
        manager.reset_account(account_id)
        return manager.get_account(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="账户不存在")


@router.get("/accounts/{account_id}/positions")
async def get_positions(account_id: str, request: Request):
    manager = _get_manager(request)
    try:
        return {"positions": manager.get_positions(account_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="账户不存在")


@router.get("/accounts/{account_id}/orders")
async def get_orders(account_id: str, request: Request):
    manager = _get_manager(request)
    try:
        return {"orders": manager.get_orders(account_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="账户不存在")


@router.get("/accounts/{account_id}/equity-curve")
async def get_equity_curve(account_id: str, request: Request, days: int = 30):
    manager = _get_manager(request)
    try:
        return {"points": manager.get_equity_curve(account_id, days=days)}
    except KeyError:
        raise HTTPException(status_code=404, detail="账户不存在")


@router.get("/accounts/{account_id}/signals")
async def get_signals(account_id: str, request: Request, limit: int = 50):
    manager = _get_manager(request)
    try:
        return {"signals": manager.get_signals(account_id, limit=limit)}
    except KeyError:
        raise HTTPException(status_code=404, detail="账户不存在")


@router.put("/accounts/{account_id}/params")
async def update_params(account_id: str, req: UpdateParamsRequest, request: Request):
    manager = _get_manager(request)
    try:
        manager.update_params(account_id, req.params)
        return manager.get_account(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="账户不存在")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/accounts/{account_id}/force-rebalance")
async def force_rebalance(account_id: str, request: Request):
    """强制策略立即调仓（无视调仓间隔天数限制）"""
    manager = _get_manager(request)
    try:
        # 先尝试获取行情（引擎可能还没启动刷新循环，直接调用 get_all_quotes 走 storage 回退）
        engine = getattr(request.app.state, "engine", None)
        if engine is not None:
            try:
                bonds = await engine.get_all_quotes()
                # 将行情注入 manager 的 market_engine.latest_quotes
                if bonds and hasattr(engine, 'latest_quotes'):
                    engine.latest_quotes = bonds
            except Exception as e:
                print(f"[ForceRebalance] get_all_quotes fallback failed: {e}")

        result = manager.force_rebalance(account_id)
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail="账户不存在")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
