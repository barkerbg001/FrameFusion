import subprocess

# Set the input and output file paths
input_file = "end/end.mp4"
output_file = "end/output.mp4"

# Set the codec options
codec_options = "-c:v libx264 -crf 18 -c:a copy"

# Build the FFmpeg command
cmd = f"ffmpeg -i {input_file} {codec_options} {output_file}"

# Call FFmpeg using subprocess
subprocess.call(cmd, shell=True)