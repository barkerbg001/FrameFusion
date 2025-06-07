from pydantic import BaseModel

class VideoBatchRequest(BaseModel):
    count: int  # How many videos to create
