# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.DeckController import DeckController
from src.backend.PageManagement.Page import Page
from src.backend.PluginManager.PluginBase import PluginBase

# Import python modules
import os

# Import gtk modules - used for the config rows
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

class SimpleAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.playing = None
        self.play_icon = os.path.join(self.plugin_base.PATH, "assets", "play.png")
        self.pause_icon = os.path.join(self.plugin_base.PATH, "assets", "pause.png")

    def on_ready(self) -> None:
        icon_path = os.path.join(self.plugin_base.PATH, "assets", "play.png")
        self.set_media(media_path=icon_path, size=0.75)
        
    def on_key_down(self) -> None:
        print("Key down")
    
    def on_key_up(self) -> None:
        print("Key up")
        if self.playing:
            self.set_media(media_path=self.play_icon, size=0.75)
        else:
            self.set_media(media_path=self.pause_icon, size=0.75)
        self.playing = not self.playing