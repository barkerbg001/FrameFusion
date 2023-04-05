import cv2
import numpy as np
import glob
import audio
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

count = 0
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
        # Read the image file and append it to the list
        img = cv2.imread(filename)
        height, width, layers = img.shape
        size = (width,height)
        img_clip = ImageClip(filename).set_duration(image_duration)
        img_array.append(img_clip)

    # Create a video writer object
    out = cv2.VideoWriter('project.avi',cv2.VideoWriter_fourcc(*'DIVX'), 1, size)

    # Write the images to the video file
    for i in range(len(img_array)):
        out.write(img_array[i])

    # Release the video writer object
    out.release()

    # Load the video and audio files
    video = VideoFileClip("project.avi")

    # Check audio and video duration
    print(f"Audio duration: {audio.duration}")
    print(f"Video duration: {video.duration}")
    
    # Add the audio to the video
    video.audio = audio

    # Increase Count by 1
    count += 1

    name = folder.replace("images/","").replace("/","")

    # Write the final videos to a file
    video.write_videofile(f"output/{name}.mp4", codec='libx264')
