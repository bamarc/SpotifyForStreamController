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

class Shuffle(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shuffle_icon = os.path.join(self.plugin_base.PATH, "assets", "shuffle.png")
        self.no_shuffle_icon = os.path.join(self.plugin_base.PATH, "assets", "no_shuffle.png")


    @property
    def get_controller(self) -> SpotifyController:
        return self.plugin_base.get_controller

    def on_ready(self) -> None:
        self.on_update()
        self.get_controller.register_update_callback(self.on_update)

    def on_key_down(self) -> None:
        shuffle = self.get_controller.toggle_shuffle()
        icon_path = self.shuffle_icon if shuffle else self.no_shuffle_icon
        self.set_media(media_path=icon_path, size=0.75)

    def on_update(self, state=None):
        shuffle = self.get_controller.get_shuffle_state(state)
        icon_path = self.shuffle_icon if shuffle else self.no_shuffle_icon
        self.set_media(media_path=icon_path, size=0.75)

    def on_key_up(self) -> None:
        pass