"""
认证 API
"""

import asyncio
import logging
import bcrypt
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt

router = APIRouter()
logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# 临时用户存储（生产环境应使用数据库）
fake_users_db = {}
_register_lock = asyncio.Lock()

class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class User(BaseModel):
    username: str
    email: str
    disabled: bool = False

class Token(BaseModel):
    access_token: str
    token_type: str

def _prehash_password(password: str) -> str:
    """预处理密码以兼容 bcrypt 的 72 字节限制。

    bcrypt 5.x 拒绝处理超过 72 字节的明文。先做一次 SHA-256 摘要，
    既固定长度又避免触发该限制。
    """
    import hashlib
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(plain_password, hashed_password):
    return bcrypt.checkpw(
        _prehash_password(plain_password).encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def get_password_hash(password):
    return bcrypt.hashpw(
        _prehash_password(password).encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")

def create_access_token(data: dict, expires_delta: timedelta = None):
    from app.config import settings
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

@router.post("/register", response_model=User)
async def register(user: UserCreate):
    try:
        if user.username in fake_users_db:
            raise HTTPException(status_code=400, detail="Username already registered")

        hashed_password = await asyncio.to_thread(get_password_hash, user.password)
        fake_users_db[user.username] = {
            "username": user.username,
            "email": user.email,
            "hashed_password": hashed_password,
            "disabled": False,
        }
        logger.info(f"[Auth] Registered user: {user.username}")
        return User(username=user.username, email=user.email)
    except HTTPException:
        raise
    except Exception as e:
        # 临时调试：某些运行时下 register 会触发 500 并导致进程退出，
        # 通过 print 确保异常信息被输出到 stderr。
        import traceback
        print(f"[REGISTER ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Registration failed: {type(e).__name__}") from e

class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = fake_users_db.get(form_data.username)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    if not await asyncio.to_thread(verify_password, form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    access_token = create_access_token(data={"sub": user["username"]})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/login", response_model=Token)
async def login_json(req: LoginRequest):
    """兼容 JSON 格式的登录请求（前端 axios 使用）"""
    user = fake_users_db.get(req.username)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    if not await asyncio.to_thread(verify_password, req.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    access_token = create_access_token(data={"sub": user["username"]})
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=User)
async def read_users_me(token: str = Depends(oauth2_scheme)):
    from app.config import settings
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = fake_users_db.get(username)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return User(username=user["username"], email=user["email"])

@router.post("/logout")
async def logout():
    return {"message": "Successfully logged out"}


# ---------------------------------------------------------------------------
# 全局认证依赖（供 router.py 使用）
# ---------------------------------------------------------------------------

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """从 JWT token 中解码并返回当前用户。"""
    from app.config import settings
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = fake_users_db.get(username)
    if user is None:
        raise credentials_exception
    return User(username=user["username"], email=user["email"])


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """验证用户是否被禁用。"""
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def verify_token(token: str = Depends(oauth2_scheme)) -> str:
    """轻量级认证依赖 —— 仅校验 token 合法性并返回 username，不查数据库。

    用于 router.py 的全局 Depends，避免在每个业务路由中重复注入。
    支持两种 token：JWT（Web 登录）或 ws_auth_token（桌面应用 IPC 代理）。
    """
    from app.config import settings
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token and token == settings.ws_auth_token:
        return "desktop"
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception


# ---------------------------------------------------------------------------
# 兼容端点：用户管理（前端 community.ts 调用）
# ---------------------------------------------------------------------------

@router.get("/user/profile")
async def get_user_profile():
    """兼容端点：获取用户信息（前端 community.ts 调用）"""
    return {"username": "desktop", "email": "", "hint": "user profile stub"}


@router.put("/user/profile")
async def update_user_profile():
    """兼容端点：更新用户信息（前端 community.ts 调用）"""
    return {"status": "ok", "hint": "user profile update stub"}


@router.put("/user/password")
async def change_user_password():
    """兼容端点：修改密码（前端 community.ts 调用）"""
    return {"status": "ok", "hint": "password change stub"}


@router.get("/user/subscriptions")
async def get_user_subscriptions():
    """兼容端点：获取用户订阅（前端 community.ts 调用）"""
    return {"subscriptions": [], "hint": "user subscriptions stub"}


@router.get("/user/strategies")
async def get_user_strategies():
    """兼容端点：获取用户策略（前端 community.ts 调用）"""
    return {"strategies": [], "hint": "user strategies stub"}
