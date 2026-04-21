from fastapi import APIRouter

from backend.crud.opensky import OpenSkyService

router = APIRouter()
service = OpenSkyService()

@router.get("/track/{icao24}")
def get_track(icao24: str, start: str, end: str):
    df = service.get_track(icao24, start, end)
    return df.to_dict(orient="records")