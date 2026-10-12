import shutil
import uuid
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Header, status
from app.core.config import MASTER_DATA_DIR
from app.services.catalog_service import catalog_service
from app.services.user_service import user_service
from app.core.security import decode_access_token

router = APIRouter(prefix="/api/master-data", tags=["Master Excel Management"])

_UPLOAD_JOBS = {}

def get_optional_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization:
        return {"username": "kartikey"}
    try:
        parts = authorization.split(" ")
        token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else authorization
        payload = decode_access_token(token)
        return payload or {"username": "kartikey"}
    except Exception:
        return {"username": "kartikey"}

@router.get("/status")
async def get_master_data_status(user: Dict[str, Any] = Depends(get_optional_user)):
    """Returns current Master Excel catalogue status for the current user."""
    username = user.get("username", "kartikey")
    u_status = user_service.get_user_master_excel_status(username)

    is_conf = u_status.get("has_master_excel", False)
    # Also fallback to catalog_service general status if user status has it
    if not is_conf and catalog_service.master_catalogue_info.get("loaded", False):
        is_conf = True

    return {
        "is_configured": is_conf,
        "username": username,
        "details": {
            **catalog_service.master_catalogue_info,
            "filename": u_status.get("filename") or catalog_service.master_catalogue_info.get("filename", "Master Catalogue"),
            "record_count": u_status.get("record_count") or catalog_service.master_catalogue_info.get("record_count", len(catalog_service.families))
        },
        "default_catalog_records": len(catalog_service.families)
    }

@router.post("/upload")
async def upload_master_excel(
    file: UploadFile = File(...),
    user: Dict[str, Any] = Depends(get_optional_user)
):
    """
    Accepts .xlsx or .xls file.
    Validates file format, stages safely per-user, parses with pandas, and updates master catalogue info.
    """
    username = user.get("username", "kartikey")
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only Excel files (.xlsx, .xls) are supported for Master Catalogue."
        )

    job_id = f"job_excel_{uuid.uuid4().hex[:8]}"
    dest_path = MASTER_DATA_DIR / f"{username}_{job_id}_{file.filename}"

    try:
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Process and validate in catalog_service
        res = catalog_service.process_master_excel(dest_path, file.filename)
        record_count = res.get("total_rows_imported", 0)

        # Persist to user record in DB
        user_service.set_user_master_excel(
            username=username,
            filename=file.filename,
            file_path=str(dest_path),
            record_count=record_count
        )

        _UPLOAD_JOBS[job_id] = {
            "job_id": job_id,
            "status": "completed",
            "username": username,
            "filename": file.filename,
            "file_size_bytes": dest_path.stat().st_size,
            "result": res
        }

        return {
            "job_id": job_id,
            "status": "completed",
            "username": username,
            "filename": file.filename,
            "file_size": dest_path.stat().st_size,
            "message": "Master Excel successfully uploaded and saved for your user account.",
            "details": res
        }
    except Exception as e:
        if dest_path.exists():
            dest_path.unlink()
        _UPLOAD_JOBS[job_id] = {
            "job_id": job_id,
            "status": "failed",
            "username": username,
            "filename": file.filename,
            "error": str(e)
        }
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to process Excel catalogue: {str(e)}"
        )

@router.get("/jobs/{job_id}")
async def get_upload_job_status(job_id: str):
    if job_id not in _UPLOAD_JOBS:
        raise HTTPException(status_code=404, detail="Job ID not found")
    return _UPLOAD_JOBS[job_id]
