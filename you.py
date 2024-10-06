from pytube import YouTube
from moviepy.editor import *
import traceback

def download_video(url, path):
    try:
        # Create YouTube object
        yt = YouTube(url)

        # Select the highest resolution stream
        video = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()

        # Download the video
        video.download(path)

        print(f"Downloaded '{yt.title}' successfully.")
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

# Replace the URL with the YouTube video link you want to download
video_url = 'https://www.youtube.com/watch?v=o8p45jI3Lb8'

# Replace with the path where you want to save the video
download_path = os.path.expanduser("~/Videos")

# Download the video
download_video(video_url, download_path)
