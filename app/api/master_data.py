import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, status
from app.core.config import MASTER_DATA_DIR
from app.services.catalog_service import catalog_service

router = APIRouter(prefix="/api/master-data", tags=["Master Excel Management"])

_UPLOAD_JOBS = {}

@router.get("/status")
async def get_master_data_status():
    """Returns current Master Excel catalogue status."""
    return {
        "is_configured": catalog_service.master_catalogue_info.get("loaded", False),
        "details": catalog_service.master_catalogue_info,
        "default_catalog_records": len(catalog_service.families)
    }

@router.post("/upload")
async def upload_master_excel(file: UploadFile = File(...)):
    """
    Accepts .xlsx or .xls file.
    Validates file format, stages safely, parses with pandas, and updates master catalogue info.
    """
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only Excel files (.xlsx, .xls) are supported for Master Catalogue."
        )

    job_id = f"job_excel_{uuid.uuid4().hex[:8]}"
    dest_path = MASTER_DATA_DIR / f"{job_id}_{file.filename}"

    try:
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Process and validate
        res = catalog_service.process_master_excel(dest_path, file.filename)
        _UPLOAD_JOBS[job_id] = {
            "job_id": job_id,
            "status": "completed",
            "filename": file.filename,
            "file_size_bytes": dest_path.stat().st_size,
            "result": res
        }

        return {
            "job_id": job_id,
            "status": "completed",
            "filename": file.filename,
            "file_size": dest_path.stat().st_size,
            "message": "Master Excel successfully uploaded and validated.",
            "details": res
        }
    except Exception as e:
        if dest_path.exists():
            dest_path.unlink()
        _UPLOAD_JOBS[job_id] = {
            "job_id": job_id,
            "status": "failed",
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
