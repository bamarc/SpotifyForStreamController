# Import StreamController modules
from typing import Optional, List
import os
import threading

from src.backend.PluginManager.ActionBase import ActionBase
from loguru import logger as log
import globals as gl

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from ...utils.SpotifyController import SpotifyController, Device


class SelectDevice(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._active_dialog = None

    @property
    def get_controller(self) -> SpotifyController:
        return self.plugin_base.get_controller

    def on_ready(self) -> None:
        icon_path = os.path.join(self.plugin_base.PATH, "assets", "media_output.png")
        self.set_media(media_path=icon_path, size=0.75)

    def on_key_down(self) -> None:
        pass

    def on_key_up(self) -> None:
        log.info(f"'{getattr(self, 'uuid', 'N/A')}' Key up - attempting to show device selection dialog.")
        devices = self._get_devices()
        GLib.idle_add(self._show_device_selection_dialog, devices)

    def _get_devices(self) -> Optional[List[Device]]:
        return self.get_controller.get_playback_devices()

    def _show_device_selection_dialog(self, devices: Optional[List[Device]]):
        """Creates and shows the Adwaita dialog for device selection on the GTK main thread."""
        parent = gl.app.get_active_window() if gl.app else None
        if self._active_dialog:
            log.warning("Device selection dialog is already open. Focusing it.")
            self._active_dialog.present(parent)
            return False

        dialog = Adw.Dialog.new()
        dialog.set_title("Select Spotify Playback Device")
        dialog.set_content_width(450)
        dialog.set_content_height(400)

        dialog_content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        dialog_content_box.set_margin_top(12)
        dialog_content_box.set_margin_bottom(12)
        dialog_content_box.set_margin_start(12)
        dialog_content_box.set_margin_end(12)

        header_bar = Adw.HeaderBar.new()
        dialog_content_box.append(header_bar)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_vexpand(True)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")

        if not devices:
            empty_label = Gtk.Label(label="No devices found.")
            empty_label.set_halign(Gtk.Align.CENTER)
            empty_label.set_valign(Gtk.Align.CENTER)
            empty_label.set_vexpand(True)
            scrolled_window.set_child(empty_label)
        else:
            group = None
            for device in devices:
                row = Adw.ActionRow(title=device.name)
                row.add_prefix(Gtk.Image.new_from_icon_name("audio-speakers-symbolic"))
                select_button = Gtk.ToggleButton.new_with_label("Play here")
                if group is None:
                    group = select_button
                else:
                    select_button.set_group(group)
                select_button.set_active(device.is_active)
                select_button.connect("toggled", self._on_select_device, device)
                row.add_suffix(select_button)
                list_box.append(row)
            scrolled_window.set_child(list_box)

        dialog_content_box.append(scrolled_window)
        dialog.set_child(dialog_content_box)

        dialog.connect("closed", self._on_close_dialog)
        self._active_dialog = dialog
        dialog.present(parent)
        return False

    def _on_close_dialog(self, dialog):
        if self._active_dialog is dialog:
            self._active_dialog = None

    def _on_select_device(self, button, device: Device):
        if not button.get_active():
            return
        threading.Thread(
            target=self.get_controller.set_playback_device,
            args=(device,),
            daemon=True,
            name="SpotifySelectDeviceThread",
        ).start()

    def _close_active_dialog(self):
        if self._active_dialog:
            dialog = self._active_dialog
            self._active_dialog = None
            dialog.force_close()
        return False

    def on_destroy(self):
        """Clean up resources when the action is destroyed."""
        log.debug(f"'{getattr(self, 'uuid', 'N/A')}' Action being destroyed. Cleaning up dialog.")
        if self._active_dialog:
            GLib.idle_add(self._close_active_dialog)
        if hasattr(super(), 'on_destroy') and callable(super().on_destroy):
            super().on_destroy()
