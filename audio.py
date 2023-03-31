import os
from moviepy.editor import *
import glob

def get_audio_file(folder_path):
    # Get a list of all files in the directory
    files = os.listdir(folder_path)
    # Use glob to filter for mp3 files
    mp3_files = glob.glob(folder_path + '/*.mp3')
    # Return the first mp3 file
    return mp3_files[0]

