# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.DeckController import DeckController
from src.backend.PageManagement.Page import Page
from src.backend.PluginManager.PluginBase import PluginBase

# Import python modules
import os
from loguru import logger as log
from GtkHelper.GenerativeUI.EntryRow import EntryRow # For regular text input
from GtkHelper.GenerativeUI.PasswordEntryRow import PasswordEntryRow # For secrets

# Import gtk modules - used for the config rows
import gi

from ...utils.SpotifyController import SpotifyController

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

class PlayResume(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.play_icon = os.path.join(self.plugin_base.PATH, "assets", "play.png")
        self.pause_icon = os.path.join(self.plugin_base.PATH, "assets", "pause.png")

    @property
    def get_controller(self) -> SpotifyController:
        return self.plugin_base.get_controller

    def on_ready(self) -> None:
        playing = self.get_controller.is_playing()
        log.info(f"Currently playing: {playing}")
        self.update_state(playing)

    def on_key_down(self) -> None:
        print("Key down")
        playing = self.get_controller.is_playing()
        log.info(f"Playback state = {playing}")
        new_state = self.get_controller.pause() if playing else self.get_controller.play()
        self.update_state(new_state)

    def update_state(self, playing : bool):
        icon_path = self.play_icon if not playing else self.pause_icon
        self.set_media(media_path=icon_path, size=0.75)

    def on_key_up(self) -> None:
        pass
