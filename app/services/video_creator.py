import os
import random
import cv2
from moviepy.editor import AudioFileClip, concatenate_audioclips, ImageClip

def create_video_from_images_and_audio(
    image_paths: list[str], 
    audio_path: str, 
    output_path: str, 
    output_name: str, 
    repeat_minutes: int
) -> str:
    from moviepy.editor import AudioFileClip, concatenate_audioclips, ImageClip
    import cv2
    import os

    original_audio = AudioFileClip(audio_path)
    target_duration = repeat_minutes * 60
    repeated = []
    dur = 0

    while dur + original_audio.duration < target_duration:
        repeated.append(original_audio.copy())
        dur += original_audio.duration

    if dur < target_duration:
        repeated.append(original_audio.subclip(0, target_duration - dur))

    final_audio = concatenate_audioclips(repeated)

    image = cv2.imread(image_paths[0])
    if image is None:
        raise FileNotFoundError(f"Image not found: {image_paths[0]}")

    resized_path = "resized_temp.jpg"
    resized = cv2.resize(image, (1920, 1080))
    cv2.imwrite(resized_path, resized)

    video_clip = ImageClip(resized_path).set_duration(final_audio.duration).set_audio(final_audio).set_fps(30)

    os.makedirs(output_path, exist_ok=True)
    output_file = os.path.join(output_path, output_name)
    video_clip.write_videofile(output_file, codec="libx264", audio_codec="aac")

    os.remove(resized_path)
    return output_file
