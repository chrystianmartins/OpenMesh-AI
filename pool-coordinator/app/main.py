from fastapi import FastAPI

app = FastAPI(title="OpenMesh Pool Coordinator", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pool-coordinator"}
