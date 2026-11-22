# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase

# Import python modules
import os

from ...utils.SpotifyController import SpotifyController

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
        if shuffle is not None:
            icon_path = self.shuffle_icon if shuffle else self.no_shuffle_icon
            self.set_media(media_path=icon_path, size=0.75)

    def on_update(self, state=None):
        shuffle = self.get_controller.get_shuffle_state(state)
        icon_path = self.shuffle_icon if shuffle else self.no_shuffle_icon
        self.set_media(media_path=icon_path, size=0.75)
        return False

    def on_key_up(self) -> None:
        pass