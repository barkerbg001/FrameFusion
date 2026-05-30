from pydantic import BaseModel


class HealthPaths(BaseModel):
    uploads: str
    output: str


class HealthResponse(BaseModel):
    status: str
    paths: HealthPaths
