import os
import json
import toga
from toga.style import Pack
from toga.constants import COLUMN, ROW
from video import setup_channel

# JSON file to store channel information
json_file = "channels.json"

def load_channels():
    if not os.path.exists(json_file):
        # Create a default JSON file if it doesn't exist
        default_data = {
            "channels": [
                {
                    "name": "Barkerbg001",
                    "picture_folder": os.path.join(os.path.expanduser("~/Pictures"), "Barkerbg001"),
                    "video_output": os.path.join(os.path.expanduser("~/Videos"), "Barkerbg001")
                }
            ]
        }
        with open(json_file, "w") as f:
            json.dump(default_data, f, indent=4)
    
    with open(json_file, "r") as f:
        data = json.load(f)
    return data["channels"]

def on_create_short(widget, channel):
    setup_channel(channel, "short")

def on_create_video(widget, channel):
    setup_channel(channel, "video")

def build(app):
    channels = load_channels()

    main_box = toga.Box(style=Pack(direction=COLUMN, padding=10))
    for channel in channels:
        channel_box = toga.Box(style=Pack(direction=ROW, padding=5))
        label = toga.Label(channel["name"], style=Pack(padding=(0, 5)))
        short_button = toga.Button(
            "Create Short",
            on_press=lambda widget, ch=channel: on_create_short(widget, ch['name']),
            style=Pack(padding=5)
        )
        video_button = toga.Button(
            "Create Video",
            on_press=lambda widget, ch=channel: on_create_video(widget, ch['name']),
            style=Pack(padding=5)
        )

        channel_box.add(label)
        channel_box.add(short_button)
        channel_box.add(video_button)
        main_box.add(channel_box)

    return main_box

if __name__ == '__main__':
    app = toga.App('Video Creator', 'org.example.videocreator', startup=build)
    app.main_loop()