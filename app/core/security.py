import hashlib
import hmac
import json
import base64
import time
from typing import Optional, Dict, Any
from fastapi import Header, HTTPException, status
from app.core.config import SECRET_KEY, TOKEN_EXPIRY_HOURS

def hash_password(password: str, salt: str = "vantis_salt_2026") -> str:
    """Hashes a password with salt using SHA-256."""
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()

def verify_password(plain_password: str, hashed_password: str, salt: str = "vantis_salt_2026") -> bool:
    """Verifies a plain password against hashed password."""
    return hmac.compare_digest(hash_password(plain_password, salt), hashed_password)

def create_access_token(data: Dict[str, Any]) -> str:
    """Generates an HMAC-SHA256 signed bearer token."""
    payload = {
        **data,
        "exp": int(time.time()) + (TOKEN_EXPIRY_HOURS * 3600),
        "iat": int(time.time())
    }
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    signature = hmac.new(SECRET_KEY.encode("utf-8"), encoded_payload.encode("utf-8"), hashlib.sha256).digest()
    encoded_sig = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
    return f"{encoded_payload}.{encoded_sig}"

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decodes and validates HMAC-SHA256 bearer token."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        encoded_payload, encoded_sig = parts
        expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), encoded_payload.encode("utf-8"), hashlib.sha256).digest()
        actual_sig = base64.urlsafe_b64decode(encoded_sig + "=" * (-len(encoded_sig) % 4))
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        payload_bytes = base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
        payload = json.loads(payload_bytes.decode("utf-8"))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None

async def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Dependency that requires a valid Bearer token."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing"
        )
    
    parts = authorization.split(" ")
    token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else authorization
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    return payload
