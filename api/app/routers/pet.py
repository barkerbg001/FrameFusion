import cv2
import glob
import random
import os
import requests
from PIL import Image
from moviepy.editor import *

# Set the directory you want to list
music_path = os.path.expanduser("~/Music")
video_path = os.path.expanduser("~/Videos")
dog_image_path = os.path.expanduser("~/DogImages")

def fetch_dog_images():
    if not os.path.exists(dog_image_path):
        os.makedirs(dog_image_path)

    png_files = []  # List to store PNG file paths
    landscape_file = None  # Variable to store the landscape image path
    mp4_file = None  # Variable to store the MP4 file path
    png_count = 0

    while png_count < 5:
        response = requests.get("https://random.dog/woof.json")
        data = response.json()
        image_url = data['url']
        print(f"Fetching {image_url}") 
        _, extension = os.path.splitext(image_url)

        try:
            # Fetch PNG images
            if extension.lower() in ['.jpg', '.jpeg','.png'] and png_count < 5:
                image_response = requests.get(image_url)
                image_name = f"dog_{png_count}.png"
                file_path = os.path.join(dog_image_path, image_name)
                with open(file_path, 'wb') as file:
                    file.write(image_response.content)
                png_files.append(file_path)
                png_count += 1

            # Fetch a landscape image
            elif extension.lower() in ['.jpg', '.jpeg'] and landscape_file is None:
                image_response = requests.get(image_url)
                image_name = "dog_landscape.jpg"
                file_path = os.path.join(dog_image_path, image_name)
                with open(file_path, 'wb') as file:
                    file.write(image_response.content)

                # Check if the image is landscape
                with Image.open(file_path) as img:
                    if img.width > img.height:
                        landscape_file = file_path
                    else:
                        os.remove(file_path)  # Remove if it's not landscape

            # Fetch an MP4 file
            elif extension.lower() in ['.mp4'] and mp4_file is None:
                video_response = requests.get(image_url)
                video_name = "dog_video.mp4"
                video_path = os.path.join(dog_image_path, video_name)
                with open(video_path, 'wb') as file:
                    file.write(video_response.content)
                mp4_file = video_path
        except Exception as e:
            print(e)

    return png_files, landscape_file, mp4_file

def create_videos(folders):
    # Create an empty list to store the images
    img_array = []

    # Iterate through all files in the current directory
    img_files = [file for file in folders if file.endswith('.jpg') or file.endswith('.png') or file.endswith('.jpeg')]
    total_files = len(img_files)

    # Load the video and audio files
    a = len(glob.glob(os.path.join(music_path, '*.mp3'))) - 1
    fileaudio = glob.glob(os.path.join(music_path, '*.mp3'))[random.randint(0, a)]
    audio = AudioFileClip(fileaudio)

    # Get the audio duration
    audio_duration = audio.duration

    # Calculate the time duration of each image
    image_duration = audio_duration / total_files

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

    # Write the final video to a file
    video.write_videofile(f"{video_path}/DogVideo.mp4", codec='libx264')

    # Delete the temporary video file
    os.remove("project.avi")

def create_shorts(folders):
    # Create an empty list to store the images
    img_array = []

    # Iterate through all files in the current directory
    img_files = [file for file in folders if file.endswith('.jpg') or file.endswith('.png') or file.endswith('.jpeg')]
    random.shuffle(img_files)

    for filename in img_files:
        # Read the image file and append it to the list
        img = cv2.imread(filename)
        height, width, layers = img.shape
        size = (width,height)
        img_array.append(img)

    # Create a video writer object
    out = cv2.VideoWriter('project.avi',cv2.VideoWriter_fourcc(*'DIVX'), 1, size)

    # Write the images to the video file
    for i in range(len(img_array)):
        out.write(img_array[i])

    # Release the video writer object
    out.release()

    # Load the video and audio files
    video = VideoFileClip("project.avi")
    a= len(glob.glob(os.path.join(music_path, '*.mp3'))) - 1
    fileaudio = glob.glob(os.path.join(music_path, '*.mp3'))[random.randint(0,a)]
    audio = AudioFileClip(fileaudio)

    # Increase the video's fps by 2
    # video = video.speedx(2) 

    # Set the duration of the video
    video.duration = len(img_array) / video.fps

    # Check if the audio and video have the same duration
    if audio.duration > video.duration:
        audio = audio.subclip(0, video.duration)
    else:
        video = video.subclip(0, audio.duration)

    # Check audio and video duration
    print(f"Audio duration: {audio.duration}")
    print(f"Video duration: {video.duration}")
        
    # Add the audio to the video
    video.audio = audio

    # Write the final videos to a file
    video.write_videofile(f"{video_path}/DogShort.mp4", codec='libx264')

def create_content(folders):
    create_shorts(folders)
    create_videos(folders)

def main():
    png_files, landscape_file, mp4_file = fetch_dog_images()

    # Print the list of file paths
    print(png_files)
    create_shorts(png_files)

main()
