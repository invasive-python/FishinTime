import os
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWTError

bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=4)
def _jwks_client(issuer: str) -> PyJWKClient:
    return PyJWKClient(f"{issuer}/.well-known/jwks.json")


def get_optional_authenticated_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer)
    ],
) -> dict[str, Any] | None:
    if credentials is None:
        return None
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization scheme")

    issuer = os.getenv("COGNITO_ISSUER", "").rstrip("/")
    client_id = os.getenv("COGNITO_CLIENT_ID")
    if not issuer or not client_id:
        raise HTTPException(
            status_code=503,
            detail="Sign-in is not configured.",
        )

    try:
        signing_key = _jwks_client(issuer).get_signing_key_from_jwt(
            credentials.credentials
        ).key
        claims = jwt.decode(
            credentials.credentials,
            signing_key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"verify_aud": False},
        )
    except PyJWKClientConnectionError as exc:
        raise HTTPException(
            status_code=503,
            detail="Sign-in verification is temporarily unavailable.",
        ) from exc
    except PyJWTError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access token",
        ) from exc

    if claims.get("token_use") != "access":
        raise HTTPException(status_code=401, detail="Invalid access token")
    if claims.get("client_id") != client_id:
        raise HTTPException(status_code=401, detail="Invalid application client")
    if not claims.get("sub"):
        raise HTTPException(status_code=401, detail="Missing user identity")

    return {
        "id": claims["sub"],
        "username": claims.get("username"),
        "email": claims.get("email"),
    }


def require_authenticated_user(
    user: Annotated[
        dict[str, Any] | None, Depends(get_optional_authenticated_user)
    ],
) -> dict[str, Any]:
    if user is None:
        raise HTTPException(status_code=401, detail="Sign-in required")
    return user
