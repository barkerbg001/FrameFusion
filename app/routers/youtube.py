from fastapi import APIRouter
from pytube import YouTube
from moviepy.editor import *
import traceback


router = APIRouter()
@router.get("/download-video")
async def download_video(url: str):
    try:
        download_path = os.path.expanduser("~/Videos")
        # Create YouTube object
        yt = YouTube(url)

        # Select the highest resolution stream
        video = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()

        # Download the video
        video.download(download_path)

        print(f"Downloaded '{yt.title}' successfully.")
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()