import os
import secrets
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_DEFAULT_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    app_name: str = "LiangHua"
    app_version: str = "1.0.0"
    host: str = "127.0.0.1"
    port: int = 8765
    debug: bool = False
    db_path: str = str(Path.home() / ".lianghua" / "market.db")
    ws_ping_interval: int = 30
    market_refresh_interval: int = 60
    trading_refresh_interval: int = 10
    off_hours_refresh_interval: int = 60
    allowed_origins: List[str] = [
        "http://localhost:5173", "http://127.0.0.1:5173",  # Vite dev server
        "http://localhost:8765", "http://127.0.0.1:8765",  # Backend direct
        "http://localhost:8766", "http://127.0.0.1:8766",  # Electron frontend server
        "null", "file://",  # Electron file:// and iframe
    ]
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
    OPENAI_MODEL: str = "gpt-4"
    ANTHROPIC_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_API_BASE: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    MINIMAX_API_KEY: str = ""
    MINIMAX_API_BASE: str = "https://api.minimaxi.chat/v1"
    MINIMAX_MODEL: str = "minimax-m3"
    TAVILY_API_KEY: str = ""
    GITHUB_TOKEN: str = ""

    # 券商 API
    EASTMONEY_API_KEY: str = ""
    HUATAI_API_KEY: str = ""
    HUATAI_API_SECRET: str = ""

    # Tushare Pro (专业金融数据)
    TUSHARE_TOKEN: str = ""

    # AKShare 代理配置
    # 注意：当代理 token 失效时，禁用代理让 AKShare 直连（macOS EM 接口可能间歇性被封，
    # 但 THS/Sina/Baidu 等多数接口可正常工作）。若需要 EM 接口稳定，请更新 token。
    AKSHARE_PROXY_GATEWAY: str = "101.201.173.125"
    AKSHARE_PROXY_TOKEN: str = ""
    AKSHARE_PROXY_ENABLED: bool = False
    AKSHARE_PROXY_RETRY: int = 5

    # 妙想 MX 金融数据
    MX_APIKEY: str = ""

    # 巨潮资讯（cninfo）在 macOS Electron 沙盒中可能失败，通过环境变量控制启用
    CNINFO_ENABLED: bool = False

    # 日志
    LOG_DIR: str = str(Path.home() / "Library" / "Logs" / "LiangHua")

    # DuckDB
    DUCKDB_VACUUM_INTERVAL_HOURS: int = 24

    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/lianghua.log"

    model_config = {
        "env_prefix": "LH_",
        "env_file": str(_DEFAULT_ENV_FILE) if _DEFAULT_ENV_FILE.exists() else None,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 双重保护：如果 pydantic-settings 从空环境变量读取了空值，
        # 但 .env 文件中有有效值，则从 .env 回退读取（override=True 避免环境变量覆盖）
        if _DEFAULT_ENV_FILE.exists():
            try:
                import dotenv
                dotenv_values = dotenv.dotenv_values(str(_DEFAULT_ENV_FILE))
                for field_name in self.model_fields:
                    env_key = f"LH_{field_name.upper()}"
                    current_val = getattr(self, field_name, "")
                    # 仅当当前值为空且 .env 中有有效值时回退
                    if not current_val and env_key in dotenv_values and dotenv_values[env_key]:
                        setattr(self, field_name, dotenv_values[env_key])
            except ImportError:
                pass

        # JWT 密钥：如果未设置则自动生成并持久化
        if not self.JWT_SECRET_KEY:
            jwt_token_file = Path.home() / ".lianghua" / ".jwt_secret"
            if jwt_token_file.exists():
                val = jwt_token_file.read_text().strip()
                if val:
                    self.JWT_SECRET_KEY = val
            if not self.JWT_SECRET_KEY:
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
                    val = token_file.read_text().strip()
                    if val:
                        self.ws_auth_token = val
                if not self.ws_auth_token:
                    self.ws_auth_token = secrets.token_urlsafe(32)
                    token_file = home_token
                    token_file.parent.mkdir(parents=True, exist_ok=True)
                    token_file.write_text(self.ws_auth_token)


settings = Settings()


def reload_settings():
    """运行时重新加载 .env 配置（仅更新用户可配置字段，不覆盖代码生成的值）
    
    注意：不重启调度器，数值字段更新后已运行的调度器间隔不会自动改变。
    """
    try:
        import dotenv
    except ImportError:
        raise RuntimeError("python-dotenv 未安装，无法热重载配置。请安装: pip install python-dotenv")
    dotenv.load_dotenv(_DEFAULT_ENV_FILE, override=False)
    new_settings = Settings()
    # 只同步简单类型字段，跳过运行时生成或路径类配置
    skip_fields = {
        'JWT_SECRET_KEY', 'ws_auth_token', 'db_path',
        'DATABASE_URL', 'LOG_DIR', 'allowed_origins',
    }
    for name in new_settings.model_fields:
        if name in skip_fields:
            continue
        val = getattr(new_settings, name)
        old = getattr(settings, name, None)
        if val != old:
            setattr(settings, name, val)
    return settings
