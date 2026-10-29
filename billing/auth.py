import os

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

ISSUER = os.environ["COGNITO_ISSUER"].rstrip("/")
CLIENT_ID = os.environ["COGNITO_CLIENT_ID"]

bearer = HTTPBearer(auto_error=False)
jwks_client = PyJWKClient(
    f"{ISSUER}/.well-known/jwks.json"
)

# TODO: narrow the exception handling to expected JWT and JWKS-fetch exceptions, and distinguish a temporary JWKS network outage from an invalid token so an infrastructure outage does not silently become a permanent authentication failure. The snippet shows the token checks but needs that refinement.

def require_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Sign-in required")

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(
            credentials.credentials
        ).key

        claims = jwt.decode(
            credentials.credentials,
            signing_key,
            algorithms=["RS256"],
            issuer=ISSUER,
            options={"verify_aud": False},
        )

        if claims.get("token_use") != "access":
            raise HTTPException(status_code=401, detail="Invalid access token")

        if claims.get("client_id") != CLIENT_ID:
            raise HTTPException(status_code=401, detail="Invalid application client")

        if not claims.get("sub"):
            raise HTTPException(status_code=401, detail="Missing user identity")

        return {
            "id": claims["sub"],
            "username": claims.get("username"),
        }

    except HTTPException:
        raise
    except (PyJWTError, Exception) as exc:
        # Replace the broad catch with the specific network/JWT exceptions
        # you want to handle in production; never log the raw token.
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access token",
        ) from exc