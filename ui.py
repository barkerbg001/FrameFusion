import os
import json
import toga
from toga.style import Pack
from toga.constants import COLUMN, ROW, CENTER
from toga import Window
from data import setup_channel, load_channels

DATA_FILE = "channels.json"

def on_create_short(widget, channel):
    setup_channel(channel, "short")

def on_create_video(widget, channel):
    setup_channel(channel, "video")

def save_channels(channels):
    with open(DATA_FILE, 'w') as f:
        json.dump({"channels": channels}, f, indent=4)

def on_add_channel(widget, name_input, picture_input, output_input, dialog):
    name = name_input.value
    picture_folder = picture_input.value
    video_output = output_input.value

    if name and picture_folder and video_output:
        new_channel = {
            "name": name,
            "picture_folder": picture_folder,
            "video_output": video_output
        }
        channels = load_channels()
        channels.append(new_channel)
        save_channels(channels)

        # Clear input fields
        name_input.value = ""
        picture_input.value = ""
        output_input.value = ""

        # Close the dialog
        dialog.close()

def create_channel_box(channel):
    channel_box = toga.Box(style=Pack(direction=ROW, padding=10, alignment=CENTER))
    label = toga.Label(
        channel["name"],
        style=Pack(padding=(0, 15), color='#00FFCC', font_size=18)
    )
    short_button = toga.Button(
        "Create Short",
        on_press=lambda widget, ch=channel: on_create_short(widget, ch['name']),
        style=Pack(padding=10, background_color='#00FFCC', color='#000000')
    )
    video_button = toga.Button(
        "Create Video",
        on_press=lambda widget, ch=channel: on_create_video(widget, ch['name']),
        style=Pack(padding=10, background_color='#FF4081', color='#FFFFFF')
    )

    channel_box.add(label)
    channel_box.add(short_button)
    channel_box.add(video_button)
    return channel_box

def build(app):
    channels = load_channels()

    main_box = toga.Box(style=Pack(direction=COLUMN, padding=20, alignment=CENTER, background_color='#1e1e1e'))
    title_label = toga.Label(
        "Video Creator",
        style=Pack(font_size=24, font_weight='bold', color='#00FFCC', padding=(0, 0, 20, 0))
    )
    main_box.add(title_label)

    for channel in channels:
        channel_box = create_channel_box(channel)
        main_box.add(channel_box)

    def show_add_channel_dialog(widget):
        # Add channel popup dialog
        dialog = Window(title='Add Channel')
        form_box = toga.Box(style=Pack(direction=COLUMN, padding=10, alignment=CENTER))
        name_input = toga.TextInput(placeholder='Channel Name', style=Pack(padding=5))
        picture_input = toga.TextInput(placeholder='Picture Folder Path', style=Pack(padding=5))
        output_input = toga.TextInput(placeholder='Video Output Path', style=Pack(padding=5))
        add_button = toga.Button(
            "Add Channel",
            on_press=lambda widget: on_add_channel(widget, name_input, picture_input, output_input, dialog),
            style=Pack(padding=10, background_color='#00FFCC', color='#000000')
        )

        form_box.add(name_input)
        form_box.add(picture_input)
        form_box.add(output_input)
        form_box.add(add_button)
        dialog.content = form_box
        dialog.show()

    # Add toolbar with option to add channel
    app.main_window.toolbar.add(
        toga.Command(
            show_add_channel_dialog,
            text='Add Channel',
            tooltip='Add a new channel',
            icon=None
        )
    )

    return main_box

if __name__ == '__main__':
    app = toga.App('Video Creator', 'org.example.videocreator', startup=build)
    app.main_loop()