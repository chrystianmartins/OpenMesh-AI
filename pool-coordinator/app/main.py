from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.jobs import router as jobs_router
from app.api.me import router as me_router
from app.api.workers import router as workers_router

app = FastAPI(title="OpenMesh Pool Coordinator", version="0.1.0")
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(workers_router)
app.include_router(jobs_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pool-coordinator"}
