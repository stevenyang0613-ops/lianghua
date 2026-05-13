from fastapi import APIRouter, Request, HTTPException

router = APIRouter()


def _get_engine(request: Request):
    return request.app.state.engine


@router.get("/quotes")
async def get_all_quotes(request: Request):
    try:
        engine = _get_engine(request)
        bonds = await engine.get_all_quotes()
        return {
            "total": len(bonds),
            "bonds": [b.model_dump() for b in bonds],
            "updated_at": engine.last_update.isoformat() if engine.last_update else "",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch quotes: {str(e)}")


@router.get("/quotes/{code}")
async def get_quote(code: str, request: Request):
    engine = _get_engine(request)
    bond = await engine.get_quote(code)
    if bond is None:
        raise HTTPException(status_code=404, detail=f"Bond {code} not found")
    return bond.model_dump()
