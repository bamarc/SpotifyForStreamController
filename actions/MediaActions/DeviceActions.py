# Import StreamController modules
from typing import Optional, List

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

from ...utils.SpotifyController import SpotifyController, Device

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

class SelectDevice(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._active_dialog = None  # To keep track of the currently open dialog

    @property
    def get_controller(self) -> SpotifyController:
        return self.plugin_base.get_controller

    def on_ready(self) -> None:
        icon_path = os.path.join(self.plugin_base.PATH, "assets", "media_output.png")
        self.set_media(media_path=icon_path, size=0.75)

    def on_key_down(self) -> None:
        print("Key down")

    def on_key_up(self) -> None:
        log.info(f"'{getattr(self, 'uuid', 'N/A')}' Key up - attempting to show device selection dialog.")
        if self._active_dialog:
            log.warning("Device selection dialog is already open. Focusing it.")
            self._active_dialog.present()  # Bring to front if already exists
            return
        self._show_device_selection_dialog()

    def _get_devices(self) -> Optional[List[Device]]:
        return self.get_controller.get_playback_devices()

    def _get_device_names(self, devices: list[Device]) -> list[str]:
        return [x.name for x in devices]

    def _get_parent_window(self) -> Gtk.Window | None:
        pass
    def _show_device_selection_dialog(self):
        """Creates and shows the Adwaita dialog for device selection."""
        #parent_window = self._get_parent_window()

        # Create the Adw.Dialog
        dialog = Adw.Dialog.new()
        #dialog.set_transient_for(parent_window)
        dialog.set_title("Select Spotify Playback Device")
        dialog.set_content_width(450)
        dialog.set_content_height(400)
        #dialog.set_default_size(450, 400)  # Adjusted size for better content visibility

        # Main content container for the dialog
        dialog_content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        # Adwaita dialogs usually handle their own padding, but margins can be added to content
        dialog_content_box.set_margin_top(12)
        dialog_content_box.set_margin_bottom(12)
        dialog_content_box.set_margin_start(12)
        dialog_content_box.set_margin_end(12)

        header_bar = Adw.HeaderBar.new()
        dialog_content_box.append(header_bar)

        # ScrolledWindow for the ListBox
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)  # Horizontal, Vertical
        scrolled_window.set_vexpand(True)  # Allow vertical expansion

        # ListBox to hold device entries
        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        # Adwaita recommends .boxed-list for lists inside other containers for proper styling
        list_box.add_css_class("boxed-list")

        # Populate with sample device names (random strings as per request for the first step)
        # In a real scenario, these would come from:
        # spotify_controller = self.get_controller
        # if spotify_controller: device_names = spotify_controller.get_available_devices()
        devices = self._get_devices()

        if not devices:
            # Handle case where no devices are found
            empty_label = Gtk.Label(label="No devices found.")
            empty_label.set_halign(Gtk.Align.CENTER)
            empty_label.set_valign(Gtk.Align.CENTER)
            empty_label.set_vexpand(True)  # Center it in the scrolled window area
            # It's better to put the label in a container that can be replaced by the list_box
            # For simplicity here, we'll set it as the child of scrolled_window if empty.
            scrolled_window.set_child(empty_label)
        else:
            group = None
            for device in devices:
                # Adw.ActionRow provides a nice, standard list item appearance
                row = Adw.ActionRow(title=device.name)
                # You can add subtitles or icons to ActionRow if needed:
                # row.set_subtitle("Available")
                row.add_prefix(Gtk.Image.new_from_icon_name("audio-speakers-symbolic"))
                select_button = Gtk.ToggleButton.new_with_label("Play here")
                select_button.set_active(device.is_active)
                if group is None:
                    group = select_button
                else:
                    select_button.set_group(group)

                select_button.connect("toggled", self._on_select_device, device)
                row.add_suffix(select_button)
                list_box.append(row)
            buttons = Adw.ButtonRow(title="Close")
            #list_box.append(buttons)
            scrolled_window.set_child(list_box)

        dialog_content_box.append(scrolled_window)
        dialog.set_child(dialog_content_box)  # Set the Gtk.Box as the dialog's main content

        # Connect to the response signal to handle button clicks
        # Pass the list_box to the handler if you don't want to retrieve it from dialog structure
        dialog.connect("closed", self._on_close_dialog, dialog)  # Pass list_box and device_names

        # Present the dialog
        dialog.present()
        self._active_dialog = dialog  # Store reference to the active dialog

    def _on_close_dialog(self, dialog):
        # It's crucial to destroy the dialog if it's not going to be reused,
        # to free up resources and allow a new one to be created next time.
        dialog.destroy()
        self._active_dialog = None  # Clear the reference

    def _on_select_device(self, dialog, device : Device):
        self.get_controller.set_playback_device(device)


    def on_destroy(self):  # Example lifecycle method, adapt if ActionBase has a different one
        """Clean up resources when the action is destroyed."""
        log.debug(f"'{getattr(self, 'uuid', 'N/A')}' Action being destroyed. Cleaning up dialog.")
        if self._active_dialog:
            self._active_dialog.destroy()
            self._active_dialog = None
        # Call super().on_destroy() if it exists in ActionBase
        if hasattr(super(), 'on_destroy') and callable(super().on_destroy):
            super().on_destroy()
