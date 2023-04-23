import cv2
import numpy as np
import glob
import audio
import random
from moviepy.editor import *
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.compositing.concatenate import concatenate_videoclips
def Combine_Videos():
    # Set the directory you want to list
    folder_path = "output"

    # Create the output directory if it doesn't exist
    if not os.path.exists("subscribe"):
        os.mkdir("subscribe")

    for item in os.listdir(folder_path):
        # Load the generated video and the existing video
        generated_video = VideoFileClip(f"{folder_path}/{item}")
        existing_video = VideoFileClip("end/end.mp4")

        # Concatenate the two videos
        final_video = concatenate_videoclips([generated_video, existing_video])

        # Get the name of the video
        name = (item.replace("\\","/")+"/").replace("output/","").replace("/","")

        # Write the final video to a file
        final_video.write_videofile(f"subscribe/{name}", codec='libx264')
