from fastapi import APIRouter

from app.engine.market import MarketEngine

router = APIRouter()
engine = MarketEngine()


@router.get("/quotes")
async def get_all_quotes():
    bonds = await engine.get_all_quotes()
    return {
        "total": len(bonds),
        "bonds": [b.model_dump() for b in bonds],
        "updated_at": engine._last_update.isoformat() if engine._last_update else "",
    }


@router.get("/quotes/{code}")
async def get_quote(code: str):
    bond = await engine.get_quote(code)
    if bond is None:
        return {"error": "not found"}
    return bond.model_dump()
