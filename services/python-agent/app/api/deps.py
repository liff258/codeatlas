"""内部接口鉴权。

Python 服务只暴露 /internal/**，且必须带 X-Internal-Token。
该 token 只存在于服务端环境变量，浏览器永远拿不到。

为什么不用 JWT：单人自用、单机部署，一个共享密钥足够，
引入 JWT 只会增加"token 过期导致演示翻车"的风险。
"""

from fastapi import Header, HTTPException, status

from app.config import settings


async def verify_internal_token(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    if not x_internal_token or x_internal_token != settings.internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid internal token",
        )
