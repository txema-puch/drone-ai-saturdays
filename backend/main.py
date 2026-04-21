from fastapi import FastAPI
from backend.api import tracks

app = FastAPI(
    title=" Anomaly Detection API",
    description="API para detectar trayectorias de anómalas usando datos de Trino.",
    version="0.1.0",
)

@app.get("/")
def read_root():
    """
    Endpoint de bienvenida.
    """
    return {"message": "Bienvenido a la API de Detección de Anomalías de Drones"}


app.include_router(tracks.router, prefix="/api", tags=["tracks"])

@app.post("/trajectories/check")
def check_trajectory():
    """
    Recibe una trayectoria y devuelve si es anómala.
    (Aquí irá la lógica de conexión a Trino y el análisis).
    """
    # TODO: Implementar la lógica de análisis
    return {"is_anomaly": False, "reason": "Not implemented yet"}
