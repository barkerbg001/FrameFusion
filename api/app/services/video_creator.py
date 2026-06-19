import os
import cv2

try:
    from moviepy import AudioFileClip, ImageClip, concatenate_audioclips
except ImportError:
    from moviepy.editor import AudioFileClip, concatenate_audioclips, ImageClip


def create_video_from_images_and_audio(
    image_paths: list[str],
    audio_path: str,
    output_path: str,
    output_name: str,
    repeat_minutes: int,
) -> str:
    original_audio = AudioFileClip(audio_path)
    target_duration = repeat_minutes * 60
    repeated = []
    dur = 0

    while dur + original_audio.duration < target_duration:
        repeated.append(original_audio.copy())
        dur += original_audio.duration

    if dur < target_duration:
        if hasattr(original_audio, "subclipped"):
            repeated.append(original_audio.subclipped(0, target_duration - dur))
        else:
            repeated.append(original_audio.subclip(0, target_duration - dur))

    final_audio = concatenate_audioclips(repeated)

    image = cv2.imread(image_paths[0])
    if image is None:
        raise FileNotFoundError(f"Image not found: {image_paths[0]}")

    resized_path = "resized_temp.jpg"
    resized = cv2.resize(image, (1920, 1080))
    cv2.imwrite(resized_path, resized)

    video_clip = ImageClip(resized_path)
    if hasattr(video_clip, "with_duration"):
        video_clip = (
            video_clip
            .with_duration(final_audio.duration)
            .with_audio(final_audio)
            .with_fps(30)
        )
    else:
        video_clip = (
            video_clip
            .set_duration(final_audio.duration)
            .set_audio(final_audio)
            .set_fps(30)
        )

    os.makedirs(output_path, exist_ok=True)
    output_file = os.path.join(output_path, output_name)
    try:
        video_clip.write_videofile(
            output_file,
            codec="libx264",
            audio_codec="aac",
        )
    finally:
        video_clip.close()
        final_audio.close()
        original_audio.close()
        os.remove(resized_path)

    return output_file
