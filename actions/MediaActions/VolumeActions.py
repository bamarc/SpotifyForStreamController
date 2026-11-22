# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase

# Import python modules
import os

from ...utils.SpotifyController import SpotifyController

class VolumeUp(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = os.path.join(self.plugin_base.PATH, "assets", "volume_up.png")

    @property
    def get_controller(self) -> SpotifyController:
        return self.plugin_base.get_controller

    def on_ready(self) -> None:
        self.set_media(media_path=self.icon, size=0.75)

    def on_key_down(self) -> None:
        current_volume = self.get_controller.get_volume()
        if current_volume is None:
            return
        self.get_controller.set_volume(min(current_volume + 10, 100))

    def on_key_up(self) -> None:
        pass

class VolumeDown(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = os.path.join(self.plugin_base.PATH, "assets", "volume_down.png")

    @property
    def get_controller(self) -> SpotifyController:
        return self.plugin_base.get_controller

    def on_ready(self) -> None:
        self.set_media(media_path=self.icon, size=0.75)

    def on_key_down(self) -> None:
        current_volume = self.get_controller.get_volume()
        if current_volume is None:
            return
        self.get_controller.set_volume(max(current_volume - 10, 0))

    def on_key_up(self) -> None:
        pass