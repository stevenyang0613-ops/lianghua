from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "LiangHua"
    host: str = "127.0.0.1"
    port: int = 8765
    debug: bool = True
    db_path: str = "data/market.db"
    ws_ping_interval: int = 30
    market_refresh_interval: int = 5
    allowed_origins: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = {"env_prefix": "LH_"}


settings = Settings()
