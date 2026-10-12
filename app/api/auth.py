import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, status
from app.schemas.models import (
    LoginRequest, LoginResponse, UserResponse,
    ResetPasswordRequest, ProfileUpdateRequest
)
from app.core.security import create_access_token, get_current_user
from app.services.user_service import user_service
from app.core.config import DATA_DIR

router = APIRouter(prefix="/api", tags=["Authentication & Profile"])

AVATARS_DIR = DATA_DIR / "avatars"
AVATARS_DIR.mkdir(parents=True, exist_ok=True)

def user_to_response(u: Dict[str, Any]) -> UserResponse:
    return UserResponse(
        id=f"usr_{u['username']}",
        username=u["username"],
        display_name=u["display_name"],
        role=u["role"],
        avatar_url=u.get("avatar_url"),
        timezone=u.get("timezone", "Asia/Kolkata"),
        notifications_enabled=bool(u.get("notifications_enabled", 1)),
        theme=u.get("theme", "light"),
        has_master_excel=bool(u.get("has_master_excel", 0)),
        master_excel_filename=u.get("master_excel_filename")
    )

@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    username = req.username.strip().lower()
    user = user_service.authenticate(username, req.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    token_data = {
        "sub": f"usr_{user['username']}",
        "username": user["username"],
        "role": user["role"]
    }
    access_token = create_access_token(token_data)

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=user_to_response(user)
    )

@router.post("/auth/logout")
async def logout():
    return {"status": "success", "message": "Successfully logged out"}

@router.get("/auth/me", response_model=UserResponse)
async def get_me(token_payload: Dict[str, Any] = Depends(get_current_user)):
    username = token_payload.get("username", "kartikey")
    user = user_service.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user_to_response(user)

@router.get("/profile", response_model=UserResponse)
async def get_profile(token_payload: Dict[str, Any] = Depends(get_current_user)):
    return await get_me(token_payload)

@router.patch("/profile", response_model=UserResponse)
async def update_profile(
    req: ProfileUpdateRequest,
    token_payload: Dict[str, Any] = Depends(get_current_user)
):
    username = token_payload.get("username", "kartikey")
    updated = user_service.update_profile(
        username=username,
        display_name=req.display_name,
        avatar_url=req.avatar_url,
        timezone=req.timezone,
        notifications_enabled=req.notifications_enabled,
        theme=req.theme
    )
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return user_to_response(updated)

@router.post("/auth/reset-password")
async def reset_password(
    req: ResetPasswordRequest,
    token_payload: Dict[str, Any] = Depends(get_current_user)
):
    username = token_payload.get("username", "kartikey")
    if not req.new_password or len(req.new_password.strip()) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters long")

    # If current_password is provided, verify it first
    if req.current_password:
        auth_check = user_service.authenticate(username, req.current_password)
        if not auth_check:
            raise HTTPException(status_code=401, detail="Current password is incorrect")

    success = user_service.reset_password(username, req.new_password.strip())
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update password")

    return {"status": "success", "message": "Password successfully updated"}

@router.post("/auth/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    token_payload: Dict[str, Any] = Depends(get_current_user)
):
    username = token_payload.get("username", "kartikey")
    ext = Path(file.filename or "avatar.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
        ext = ".png"

    dest_file = AVATARS_DIR / f"{username}{ext}"
    with open(dest_file, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Convert to data URL or relative URL
    avatar_url = f"/api/avatars/{username}{ext}"
    user_service.update_profile(username=username, avatar_url=avatar_url)

    return {"status": "success", "avatar_url": avatar_url}
