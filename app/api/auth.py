from fastapi import APIRouter, HTTPException, Depends, status
from typing import Dict, Any
from app.schemas.models import LoginRequest, LoginResponse, UserResponse, ProfileUpdateRequest
from app.core.security import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/api", tags=["Authentication & Profile"])

# In-memory user store (can be persisted or updated)
_CURRENT_USER = {
    "id": "usr_vantis_001",
    "email": "employee@columbia.com",
    "password_hash": hash_password("vantis2026"),
    "display_name": "Kartikey Columbia Admin",
    "role": "Product Intelligence Lead",
    "avatar_url": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80",
    "timezone": "Asia/Kolkata",
    "notifications_enabled": True,
    "theme": "light"
}

@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    # Support any valid email with default or existing demo password, or create demo employee
    email = req.email.strip().lower()
    
    # Check if matches current user or allow valid corporate login
    if email == _CURRENT_USER["email"] and not verify_password(req.password, _CURRENT_USER["password_hash"]):
        # Also allow if password is "vantis2026" or "admin123"
        if req.password not in ("vantis2026", "admin123", "password"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

    token_data = {
        "sub": _CURRENT_USER["id"],
        "email": email,
        "role": _CURRENT_USER["role"]
    }
    access_token = create_access_token(token_data)

    user_resp = UserResponse(
        id=_CURRENT_USER["id"],
        email=email,
        display_name=_CURRENT_USER["display_name"],
        role=_CURRENT_USER["role"],
        avatar_url=_CURRENT_USER["avatar_url"],
        timezone=_CURRENT_USER["timezone"],
        notifications_enabled=_CURRENT_USER["notifications_enabled"],
        theme=_CURRENT_USER["theme"]
    )

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=user_resp
    )

@router.post("/auth/logout")
async def logout():
    return {"status": "success", "message": "Successfully logged out"}

@router.get("/auth/me", response_model=UserResponse)
async def get_me(user: Dict[str, Any] = Depends(get_current_user)):
    return UserResponse(
        id=_CURRENT_USER["id"],
        email=user.get("email", _CURRENT_USER["email"]),
        display_name=_CURRENT_USER["display_name"],
        role=_CURRENT_USER["role"],
        avatar_url=_CURRENT_USER["avatar_url"],
        timezone=_CURRENT_USER["timezone"],
        notifications_enabled=_CURRENT_USER["notifications_enabled"],
        theme=_CURRENT_USER["theme"]
    )

@router.get("/profile", response_model=UserResponse)
async def get_profile(user: Dict[str, Any] = Depends(get_current_user)):
    return await get_me(user)

@router.patch("/profile", response_model=UserResponse)
async def update_profile(
    req: ProfileUpdateRequest,
    user: Dict[str, Any] = Depends(get_current_user)
):
    global _CURRENT_USER
    if req.display_name is not None:
        _CURRENT_USER["display_name"] = req.display_name.strip()
    if req.avatar_url is not None:
        _CURRENT_USER["avatar_url"] = req.avatar_url.strip()
    if req.timezone is not None:
        _CURRENT_USER["timezone"] = req.timezone.strip()
    if req.notifications_enabled is not None:
        _CURRENT_USER["notifications_enabled"] = req.notifications_enabled
    if req.theme is not None:
        _CURRENT_USER["theme"] = req.theme.strip()

    return UserResponse(
        id=_CURRENT_USER["id"],
        email=user.get("email", _CURRENT_USER["email"]),
        display_name=_CURRENT_USER["display_name"],
        role=_CURRENT_USER["role"],
        avatar_url=_CURRENT_USER["avatar_url"],
        timezone=_CURRENT_USER["timezone"],
        notifications_enabled=_CURRENT_USER["notifications_enabled"],
        theme=_CURRENT_USER["theme"]
    )
