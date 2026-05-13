# backend/app/api/market.py
from fastapi import APIRouter

router = APIRouter()


@router.get("/quotes")
async def get_all_quotes():
    return {"total": 0, "bonds": [], "updated_at": ""}
