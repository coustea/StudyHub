from datetime import UTC, datetime, timedelta

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.config.config import JwtConfig, get_settings
from app.core.exceptions import AuthenticationError

password_hasher = PasswordHash((Argon2Hasher(),))


def hash_password(plain_password: str) -> str:
    """使用 Argon2 对明文密码进行哈希加密。"""
    return password_hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与已存储的 Argon2 哈希是否匹配。"""
    return password_hasher.verify(plain_password, hashed_password)


def _create_token(
    user_id: int,
    username: str,
    token_type: str,
    expires_delta: timedelta,
    jwt_cfg: JwtConfig,
) -> str:
    """生成指定类型与有效期的 JWT 字符串。"""
    payload = {
        "sub": str(user_id),
        "username": username,
        "type": token_type,
        "exp": int((datetime.now(UTC) + expires_delta).timestamp()),
    }
    return jwt.encode(payload, jwt_cfg.secret_key, algorithm=jwt_cfg.algorithm)


def create_tokens(user_id: int, username: str) -> tuple[str, str, int]:
    """为用户签发访问令牌与刷新令牌。

    Args:
        user_id: 用户主键 ID。
        username: 用户名。

    Returns:
        由 (access_token, refresh_token, access_expires_in_seconds) 组成的三元组。
    """
    jwt_cfg = get_settings().jwt
    access_delta = timedelta(minutes=jwt_cfg.access_token_expire_minutes)
    refresh_delta = timedelta(days=jwt_cfg.refresh_token_expire_days)

    access_token = _create_token(user_id, username, "access", access_delta, jwt_cfg)
    refresh_token = _create_token(user_id, username, "refresh", refresh_delta, jwt_cfg)
    return access_token, refresh_token, int(access_delta.total_seconds())


def decode_token(token: str, expected_type: str = "access") -> tuple[int, str]:
    """解析并校验 JWT 令牌，提取用户 ID 与用户名。

    Args:
        token: 客户端传入的 JWT 字符串。
        expected_type: 期望的令牌类型（access 或 refresh）。

    Returns:
        校验通过的 (user_id, username) 二元组。

    Raises:
        AuthenticationError: 令牌无效、过期、类型不匹配或载荷字段缺失时抛出。
    """
    jwt_cfg = get_settings().jwt
    try:
        raw = jwt.decode(
            token,
            jwt_cfg.secret_key,
            algorithms=[jwt_cfg.algorithm],
            options={"require": ["sub", "username", "type", "exp"]},
        )
    except InvalidTokenError as exc:
        raise AuthenticationError("无效或已过期的认证令牌。") from exc

    if raw.get("type") != expected_type:
        raise AuthenticationError("认证令牌类型无效。")

    try:
        user_id = int(raw["sub"])
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("认证令牌主体格式无效。") from exc

    username = str(raw["username"]).strip()
    if not username:
        raise AuthenticationError("认证令牌缺少用户名。")

    return user_id, username
