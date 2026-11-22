# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase

# Import python modules
import os

from ...utils.SpotifyController import SpotifyController


class Previous(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @property
    def get_controller(self) -> SpotifyController:
        return self.plugin_base.get_controller

    def on_ready(self) -> None:
        icon_path = os.path.join(self.plugin_base.PATH, "assets", "previous.png")
        self.set_media(media_path=icon_path, size=0.75)

    def on_key_down(self) -> None:
        self.get_controller.previous_track()

    def on_key_up(self) -> None:
        pass