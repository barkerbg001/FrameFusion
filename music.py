import cv2
import numpy
import glob
import os
import random
from moviepy.editor import *

# Set the directory you want to list
folder_path = "images"
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
    img_files = glob.glob(folder+'*.png')
    random.shuffle(img_files)

    # Load the audio file
    a = len(glob.glob('audio/*.mp3')) - 1
    fileaudio = glob.glob('audio/*.mp3')[random.randint(0,a)]
    audio = AudioFileClip(fileaudio)

    # Calculate the duration of each image
    image_duration = audio.duration / len(img_files)

    for filename in img_files:
        # Read the image file and repeat it for the required duration
        img = cv2.imread(filename)
        img_clip = ImageClip(filename).set_duration(image_duration)
        img_array.append(img_clip)

    # Concatenate the image clips to create the video clip
    video = concatenate_videoclips(img_array)

    # Add the audio to the video
    video.audio = audio

    name = folder.replace("images/","").replace("/","")

    # Write the final video to a file
    video.fps = 25
    video.write_videofile(f"output/{name}.mp4", codec='libx264')
