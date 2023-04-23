import cv2
import glob
import random
from moviepy.editor import *

# Set the directory you want to list
music_path = os.path.expanduser("~/Music")
photo_path = os.path.expanduser("~/Pictures")
video_path = os.path.expanduser("~/Videos")

def create_videos(channelname, folder, output_path):
    # Create an empty list to store the images
    img_array = []

    # Iterate through all PNG files in the current directory
    img_files = sorted(glob.glob(folder+'*.png'))
    total_imgs = len(img_files)
    if total_imgs == 0:
        print(f"No images found in folder: {folder}")
        return

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
    name = folder.replace(photo_path.replace("\\","/")+"/","").replace(f"{channelname}/","").replace("/","")

    # Write the final video to a file
    video.write_videofile(f"{output_path}/{name}.mp4", codec='libx264')

    # Delete the temporary video file
    os.remove("project.avi")

def create_shorts(channelname, folder, output_path):
    # Create an empty list to store the images
    img_array = []

    # Iterate through all PNG files in the current directory
    img_files = glob.glob(folder+'*.png')
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

    name = folder.replace(photo_path.replace("\\","/")+"/","").replace(f"{channelname}/","").replace("/","")

    # Write the final videos to a file
    video.write_videofile(f"{output_path}/{name}.mp4", codec='libx264')

def get_image_orientation(folder_path):
    # Get a list of all files in the folder
    files = os.listdir(folder_path)
    # Filter the list to include only image files
    image_files = [file for file in files if file.endswith('.jpg') or file.endswith('.png')]
    # Choose a random image file from the list
    image_file = random.choice(image_files)
    # Open the image file using OpenCV
    image_path = os.path.join(folder_path, image_file)
    img = cv2.imread(image_path)
    # Get the width and height of the image
    height, width, channels = img.shape
    # Determine if the image is landscape or portrait
    if width > height:
        return 'landscape'
    else:
        return 'portrait'
    
def create_content(channelname, folders, output_path):
    for folder in folders:
        orientation = get_image_orientation(folder)

        if orientation == 'portrait':
            create_shorts(channelname, folder, output_path)
        else:
            create_videos(channelname, folder, output_path)

def setup_channel(brandname, type = ""):
    channelname = f"{brandname} {type}".strip()
    folders = []

    # Create the input directory if it doesn't exist
    folder_path = os.path.join(photo_path,channelname)
    if not os.path.exists(folder_path):
        os.mkdir(folder_path)

    # Create the output directory if it doesn't exist
    output_path = os.path.join(video_path,channelname)
    if not os.path.exists(output_path):
        os.mkdir(output_path)

    for item in os.listdir(folder_path):
        item_path = os.path.join(folder_path, item)
        if os.path.isdir(item_path):
            folders.append(item_path.replace("\\","/")+"/")

    # Print the list of folders
    print(folders)
    create_content(channelname, folders, output_path)
    

def main(brandname):
    setup_channel(brandname)
    setup_channel(brandname, "Gaming")
    setup_channel(brandname, "Shorts")

main("Barkerbg001")
