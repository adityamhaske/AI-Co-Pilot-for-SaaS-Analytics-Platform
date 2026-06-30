from datetime import datetime, timedelta
from typing import Any, Union
from jose import jwt
import bcrypt
from app.core.config import settings

ALGORITHM = "HS256"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def create_access_token(
    subject: Union[str, Any], tenant_id: str, role: str, expires_delta: timedelta = None
) -> str:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "tenant_id": tenant_id,
        "role": role,
    }
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    return payload
