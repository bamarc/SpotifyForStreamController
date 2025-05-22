# Import StreamController modules
from PIL.ImageFile import ImageFile
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.DeckController import DeckController
from src.backend.PageManagement.Page import Page
from src.backend.PluginManager.PluginBase import PluginBase

# Import python modules
import io
import os
import requests
from PIL import Image
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
        self.update_state()

    def on_key_down(self) -> None:
        print("Key down")
        playing = self.get_controller.is_playing()
        log.info(f"Playback state = {playing}")
        new_state = self.get_controller.pause() if playing else self.get_controller.play()
        self.update_state()

    def load_overlay(self, icon_path):
        try:
            with Image.open(icon_path) as icon_img:
                # Ensure it has an alpha channel if it's transparent
                icon_pil_image = icon_img.convert("RGBA")
                #self.show_overlay(image=icon_pil_image)
                log.info(f"Successfully showed overlay icon from {icon_path}.")
                return icon_pil_image.copy()

                # If you want the overlay to disappear after some time, specify 'duration' in seconds
                # self.show_overlay(image=icon_pil_image, duration=5)
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
        Scales an icon to fit within 90% of the background's dimensions,
        maintaining aspect ratio, and merges it onto the center of the background.

        Args:
            background_img: A PIL Image object for the background.
            icon_img: A PIL Image object for the icon.

        Returns:
            A new PIL Image object with the icon composited onto the background.
        """
        if not background_img or not icon_img:
            raise ValueError("Both background and icon images must be provided.")

        # Ensure images are in RGBA format to handle transparency properly
        bg_img = background_img.convert("RGBA")
        ic_img = icon_img.convert("RGBA")

        bg_width, bg_height = bg_img.size
        icon_width, icon_height = ic_img.size

        # 1. Calculate target dimensions for the icon (to fit within 90% of background)
        # The icon should fit within a container that is 90% of the background size.
        target_container_width = bg_width * 0.70
        target_container_height = bg_height * 0.70

        # Calculate scaling ratios for width and height
        width_ratio = target_container_width / icon_width
        height_ratio = target_container_height / icon_height

        # Use the smaller ratio to ensure the icon fits while maintaining aspect ratio
        scale_factor = min(width_ratio, height_ratio)

        # New icon dimensions
        new_icon_width = int(icon_width * scale_factor)
        new_icon_height = int(icon_height * scale_factor)

        # 2. Resize the icon
        # Ensure dimensions are at least 1px if scaling down very small icons
        if new_icon_width < 1: new_icon_width = 1
        if new_icon_height < 1: new_icon_height = 1

        scaled_icon_img = ic_img.resize((new_icon_width, new_icon_height), Image.Resampling.LANCZOS)

        # 3. Calculate position for centering the scaled icon
        # Use the actual dimensions of the scaled icon
        scaled_icon_actual_width, scaled_icon_actual_height = scaled_icon_img.size
        pos_x = (bg_width - scaled_icon_actual_width) // 2
        pos_y = (bg_height - scaled_icon_actual_height) // 2
        position = (pos_x, pos_y)

        # 4. Composite the images
        # Create a copy of the background to paste onto
        output_img = bg_img.copy()
        # Paste the scaled icon using its alpha channel as a mask
        output_img.paste(scaled_icon_img, position, mask=scaled_icon_img)

        return output_img


    def load_background_media(self) -> Image.Image | None:
        # try to get album art
        try:
            album_image_url = self.get_controller.get_playback_art()
            if album_image_url:
                # Fetch the image from the URL
                response = requests.get(album_image_url, stream=True)
                response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
                log.info(f"got image from {album_image_url}")

                # Open the image from the response content
                # Using io.BytesIO to treat the byte stream like a file
                background_pil_image = Image.open(io.BytesIO(response.content))

                # Set the media using the PIL Image object
                # .copy() is good practice if you intend to reuse the PIL image object elsewhere
                #self.set_media(image=background_pil_image.copy(), media_path=icon_path)
                log.info("Successfully retrieved background image from URL.")
                return background_pil_image.copy()
            else:
                return None
        except requests.exceptions.RequestException as e:
            log.error(f"Error fetching background image from URL {album_image_url}: {e}")
            # Optionally, set a fallback background or show an error state
            # self.set_background_color([255, 0, 0, 255]) # Example: Red background on error
        except IOError as e:
            log.error(f"Error opening background image from URL (PIL failed): {e}")
        except Exception as e:
            log.error(f"An unexpected error occurred while setting background: {e}")



    def update_state(self):
        playing = self.get_controller.is_playing()
        icon_path = self.play_icon if not playing else self.pause_icon
        background = self.load_background_media()
        icon = self.load_overlay(icon_path)
        combined = self.merge_icon_on_background_centered(background, icon)
        self.set_media(image=combined.copy())




def on_key_up(self) -> None:
        pass
