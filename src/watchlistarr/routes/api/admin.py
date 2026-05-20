from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/refresh/{job_id}")
async def trigger_refresh(job_id: str, request: Request) -> dict[str, str]:
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="scheduler no inicializado")
    ok = await scheduler.trigger_now(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"job {job_id!r} no existe")
    return {"status": "triggered", "job_id": job_id}


@router.post("/scheduler/sync")
async def sync_scheduler(request: Request) -> dict[str, int]:
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="scheduler no inicializado")
    await scheduler.sync_jobs()
    return {"jobs": len(scheduler.jobs)}
