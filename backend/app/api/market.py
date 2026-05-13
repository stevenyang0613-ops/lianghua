from fastapi import APIRouter, Request

router = APIRouter()


def _get_engine(request: Request):
    return request.app.state.engine


@router.get("/quotes")
async def get_all_quotes(request: Request):
    engine = _get_engine(request)
    bonds = await engine.get_all_quotes()
    return {
        "total": len(bonds),
        "bonds": [b.model_dump() for b in bonds],
        "updated_at": engine._last_update.isoformat() if engine._last_update else "",
    }


@router.get("/quotes/{code}")
async def get_quote(code: str, request: Request):
    engine = _get_engine(request)
    bond = await engine.get_quote(code)
    if bond is None:
        return {"error": "not found"}
    return bond.model_dump()
