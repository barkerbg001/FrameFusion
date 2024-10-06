from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Horizontal
from textual.widgets import Button, Footer, Header, Static, Label
import cv2
import glob
import random
from moviepy.editor import *
from video import setup_channel



class Channel(Static):
    """A channel widget."""
    value = Static

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Event handler called when a button is pressed."""
        setup_channel(self.id, event.button.id)

    def compose(self) -> ComposeResult:
        """Create child widgets of a channel."""
        
        yield Label(self.id)
        yield Button("Video", id="video")
        yield Button("Shorts", id="shorts", variant="primary")


class FrameFusionApp(App):
    CSS_PATH = "style.css"
    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Footer()
        yield ScrollableContainer(Channel(id="Barkerbg001"), Channel(id="Barkerbg001 Gaming"),Channel(id="Barkerbg001 Shorts"),Channel(id="Barkerbg001 Programming"), Channel(id="Barkify"))

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.dark = not self.dark


if __name__ == "__main__":
    app = FrameFusionApp()
    app.run()
