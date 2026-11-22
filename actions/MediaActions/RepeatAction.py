# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase

# Import python modules
import os

from ...utils.SpotifyController import SpotifyController

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
        idx = (self.repeat_states.index(repeat) + 1) % len(self.repeat_states) if repeat in self.repeat_states else 0
        next_state = self.repeat_states[idx]
        if self.get_controller.set_repeat_state(next_state):
            self.set_media(media_path=self.icon_paths[idx], size=0.75)

    def on_update(self, state=None):
        repeat_state = self.get_controller.get_repeat_state(state)
        idx = self.repeat_states.index(repeat_state) if repeat_state in self.repeat_states else 0
        self.set_media(media_path=self.icon_paths[idx], size=0.75)
        return False

    def on_key_up(self) -> None:
        pass