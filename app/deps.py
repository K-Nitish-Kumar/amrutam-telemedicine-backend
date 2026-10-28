from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import decode_token
from app.config import get_settings

bearer = HTTPBearer(auto_error=False)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        user_id = decode_token(credentials.credentials)
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired access token") from None
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account disabled or not found")
    # An access token issued before MFA enrollment MUST NOT become privileged after enrollment.
    if user.mfa_enabled:
        data = jwt.decode(credentials.credentials, get_settings().jwt_secret,
                          algorithms=["HS256"], issuer="amrutam-api", audience="amrutam-client")
        if data.get("mfa_verified") is not True:
            raise HTTPException(status_code=401, detail="MFA-verified login required")
    return user


def require_roles(*roles: str) -> Callable:
    def check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        if user.role in ("admin", "doctor") and not user.mfa_enabled:
            raise HTTPException(status_code=403, detail="MFA enrollment required for privileged role")
        return user
    return check
