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

class Repeat(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.repeat_context_icon = os.path.join(self.plugin_base.PATH, "assets", "repeat.png")
        self.repeat_one_icon = os.path.join(self.plugin_base.PATH, "assets", "repeat_one.png")
        self.no_repeat_icon = os.path.join(self.plugin_base.PATH, "assets", "no_repeat.png")
        self.repeat_states = ["off", "track", "context"]
        self.icon_paths = [self.no_repeat_icon, self.repeat_one_icon, self.repeat_context_icon]

    @property
    def get_controller(self) -> SpotifyController:
        return self.plugin_base.get_controller

    def on_ready(self) -> None:
        self.on_update()
        self.get_controller.register_update_callback(self.on_update)

    def on_key_down(self) -> None:
        repeat = self.get_controller.get_repeat_state()
        idx = max((self.repeat_states.index(repeat)+1)%3,0)
        next_state = self.repeat_states[idx]
        next_state_icon = self.repeat_context_icon[idx]
        self.get_controller.set_repeat(next_state)
        self.set_media(media_path=next_state_icon, size=0.75)

    def on_update(self, state=None):
        repeat_state = self.get_controller.get_repeat_state(state)
        icon = self.icon_paths[self.repeat_states.index(repeat_state)]
        self.set_media(media_path=icon, size=0.75)

    def on_key_up(self) -> None:
        pass