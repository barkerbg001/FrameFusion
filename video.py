import cv2
import numpy as np
import glob
import os
import random
from moviepy.editor import *

# Set the directory you want to list
folder_path = "images"
music_path = os.path.expanduser("~/Music")
folders = []

# Create the output directory if it doesn't exist
if not os.path.exists("output"):
    os.mkdir("output")

for item in os.listdir(folder_path):
    item_path = os.path.join(folder_path, item)
    if os.path.isdir(item_path):
        folders.append(item_path.replace("\\","/")+"/")

# Print the list of folders
print(folders)

for folder in folders:
    # Create an empty list to store the images
    img_array = []

    # Iterate through all PNG files in the current directory
    img_files = sorted(glob.glob(folder+'*.png'))
    total_imgs = len(img_files)
    if total_imgs == 0:
        print(f"No images found in folder: {folder}")
        continue

    # Load the video and audio files
    a = len(glob.glob(os.path.join(music_path, '*.mp3'))) - 1
    fileaudio = glob.glob(os.path.join(music_path, '*.mp3'))[random.randint(0, a)]
    audio = AudioFileClip(fileaudio)

    # Get the audio duration
    audio_duration = audio.duration

    # Calculate the time duration of each image
    image_duration = audio_duration / total_imgs

    # Create a VideoWriter object
    size = cv2.imread(img_files[0]).shape[:2][::-1]
    out = cv2.VideoWriter('project.avi',cv2.VideoWriter_fourcc(*'DIVX'), 30, size)

    # Loop through each image file and add it to the video
    for i, filename in enumerate(img_files):
        # Read the image file
        img = cv2.imread(filename)

        # Write the image to the video for the calculated duration
        for j in range(int(image_duration*30)):
            out.write(img)

        # Append the image to the image array
        img_array.append(img)

    # Release the video writer object
    out.release()

    # Create a moviepy video clip from the video file
    video = VideoFileClip("project.avi")

    # Set the duration of the video clip to be the same as the audio duration
    video_duration = audio_duration
    video = video.set_duration(video_duration)

    # Check if the audio and video have the same duration
    if audio_duration > video_duration:
        audio = audio.subclip(0, video_duration)
    else:
        video = video.subclip(0, audio_duration)

    # Check audio and video duration
    print(f"Audio duration: {audio.duration}")
    print(f"Video duration: {video.duration}")

    # Add the audio to the video clip
    video = video.set_audio(audio)

    # Get the name of the current folder
    name = folder.replace("images/","").replace("/","")

    # Write the final video to a file
    video.write_videofile(f"output/{name}.mp4", codec='libx264')

    # Delete the temporary video file
    os.remove("project.avi")
