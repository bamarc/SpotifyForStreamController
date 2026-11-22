# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase

# Import python modules
import io
import os
import threading
import requests
from PIL import Image
from loguru import logger as log
from gi.repository import GLib

from ...utils.SpotifyController import SpotifyController


class PlayResume(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.play_icon = os.path.join(self.plugin_base.PATH, "assets", "play.png")
        self.pause_icon = os.path.join(self.plugin_base.PATH, "assets", "pause.png")
        self._cached_art_url = None
        self._cached_art_image = None
        self._desired_art_url = None
        self._desired_playing = False

    @property
    def get_controller(self) -> SpotifyController:
        return self.plugin_base.get_controller

    def on_ready(self) -> None:
        self.update_state()
        self.get_controller.register_update_callback(self.update_state)

    def on_key_down(self) -> None:
        playing = self.get_controller.is_playing()
        log.info(f"Playback state = {playing}")
        ok = self.get_controller.pause() if playing else self.get_controller.play()
        if ok:
            optimistic_state = dict(self.get_controller.latest_playback_state or {}, is_playing=not playing)
            GLib.idle_add(self.update_state, optimistic_state)

    def load_overlay(self, icon_path):
        try:
            with Image.open(icon_path) as icon_img:
                icon_pil_image = icon_img.convert("RGBA")
                return icon_pil_image.copy()
        except FileNotFoundError:
            log.error(f"Error: Overlay icon file not found at {icon_path}")
        except IOError as e:
            log.error(f"Error opening overlay icon (PIL failed): {e}")
        except Exception as e:
            log.error(f"An unexpected error occurred while setting overlay: {e}")

    def merge_icon_on_background_centered(
            self,
            background_img: Image.Image,
            icon_img: Image.Image
    ) -> Image.Image:
        """
        Scales an icon to fit within 70% of the background's dimensions,
        maintaining aspect ratio, and merges it onto the center of the background.
        """
        if background_img is None or icon_img is None:
            raise ValueError("Both background and icon images must be provided.")

        bg_img = background_img.convert("RGBA")
        ic_img = icon_img.convert("RGBA")

        bg_width, bg_height = bg_img.size
        icon_width, icon_height = ic_img.size

        target_container_width = bg_width * 0.70
        target_container_height = bg_height * 0.70

        scale_factor = min(target_container_width / icon_width, target_container_height / icon_height)
        new_icon_width = max(1, int(icon_width * scale_factor))
        new_icon_height = max(1, int(icon_height * scale_factor))

        scaled_icon_img = ic_img.resize((new_icon_width, new_icon_height), Image.Resampling.LANCZOS)
        pos_x = (bg_width - scaled_icon_img.size[0]) // 2
        pos_y = (bg_height - scaled_icon_img.size[1]) // 2

        output_img = bg_img.copy()
        output_img.paste(scaled_icon_img, (pos_x, pos_y), mask=scaled_icon_img)
        return output_img

    def load_background_media(self, album_image_url: str | None) -> Image.Image | None:
        if not album_image_url:
            return None
        try:
            response = requests.get(album_image_url, timeout=10)
            response.raise_for_status()
            with Image.open(io.BytesIO(response.content)) as background_pil_image:
                return background_pil_image.copy()
        except requests.exceptions.RequestException as e:
            log.error(f"Error fetching background image from URL {album_image_url}: {e}")
        except IOError as e:
            log.error(f"Error opening background image from URL (PIL failed): {e}")
        except Exception as e:
            log.error(f"An unexpected error occurred while setting background: {e}")
        return None

    def _render_button(self, playing: bool | None, background: Image.Image | None):
        icon_path = self.pause_icon if playing else self.play_icon
        icon = self.load_overlay(icon_path)
        if background and icon:
            combined = self.merge_icon_on_background_centered(background, icon)
            self.set_media(image=combined)
        elif icon:
            self.set_media(image=icon)

    def _fetch_art_async(self, album_url: str):
        image = self.load_background_media(album_url)
        GLib.idle_add(self._on_art_loaded, album_url, image)

    def _on_art_loaded(self, album_url: str, image: Image.Image | None):
        if album_url != self._desired_art_url:
            return False
        self._cached_art_url = album_url
        self._cached_art_image = image
        self._render_button(self._desired_playing, image)
        return False

    def update_state(self, state=None):
        playing = self.get_controller.is_playing(state)
        album_url = self.get_controller.get_playback_art_url(state)
        self._desired_playing = playing
        self._desired_art_url = album_url

        if not album_url:
            self._cached_art_url = None
            self._cached_art_image = None
            self._render_button(playing, None)
        elif album_url == self._cached_art_url:
            self._render_button(playing, self._cached_art_image)
        else:
            # Show icon immediately, then composite cover art once downloaded off the UI thread.
            self._render_button(playing, None)
            threading.Thread(
                target=self._fetch_art_async,
                args=(album_url,),
                daemon=True,
                name="SpotifyCoverArtThread",
            ).start()
        return False

    def on_key_up(self) -> None:
        pass
