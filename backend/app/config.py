import os
import secrets
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "LiangHua"
    app_version: str = "1.0.0"
    host: str = "127.0.0.1"
    port: int = 8765
    debug: bool = False
    db_path: str = str(Path(__file__).parent.parent / "data" / "market.db")
    ws_ping_interval: int = 30
    market_refresh_interval: int = 60
    trading_refresh_interval: int = 10
    off_hours_refresh_interval: int = 60
    allowed_origins: List[str] = ["http://localhost:5173", "http://localhost:8765", "null", "file://"]
    ws_auth_token: str = ""

    # SQLAlchemy 数据库 (AI/认证模块使用)
    DATABASE_URL: str = "sqlite+aiosqlite:///./lianghua.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    # ⚠ 必须在生产环境通过环境变量 LH_JWT_SECRET_KEY 覆盖此默认值
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # AI 配置
    OPENAI_API_KEY: str = ""
    OPENAI_API_BASE: str = "https://api.openai.com/v1"
    ANTHROPIC_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_API_BASE: str = "https://api.deepseek.com/v1"

    # 券商 API
    EASTMONEY_API_KEY: str = ""
    HUATAI_API_KEY: str = ""
    HUATAI_API_SECRET: str = ""

    # 日志
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/lianghua.log"

    model_config = {"env_prefix": "LH_"}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # JWT 密钥：如果未设置则自动生成并持久化
        if not self.JWT_SECRET_KEY:
            jwt_token_file = Path.home() / ".lianghua" / ".jwt_secret"
            if jwt_token_file.exists():
                self.JWT_SECRET_KEY = jwt_token_file.read_text().strip()
            else:
                self.JWT_SECRET_KEY = secrets.token_urlsafe(32)
                jwt_token_file.parent.mkdir(parents=True, exist_ok=True)
                jwt_token_file.write_text(self.JWT_SECRET_KEY)
        if not self.ws_auth_token:
            token_env = os.environ.get("LH_WS_AUTH_TOKEN", "")
            if token_env:
                self.ws_auth_token = token_env
            else:
                # 优先使用 ~/.lianghua/.ws_token（Electron 桌面应用路径）
                home_token = Path.home() / ".lianghua" / ".ws_token"
                # 回退到源码目录下的 data/.ws_token（开发环境路径）
                local_token = Path(__file__).parent.parent / "data" / ".ws_token"
                token_file = home_token if home_token.exists() else local_token
                if token_file.exists():
                    self.ws_auth_token = token_file.read_text().strip()
                else:
                    self.ws_auth_token = secrets.token_urlsafe(32)
                    token_file = home_token
                    token_file.parent.mkdir(parents=True, exist_ok=True)
                    token_file.write_text(self.ws_auth_token)


settings = Settings()
