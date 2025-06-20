# Import StreamController modules
from src.backend.PluginManager.PluginBase import PluginBase
from src.backend.PluginManager.ActionHolder import ActionHolder

from .utils.SpotifyController import AuthController
from .utils.SpotifyController import SpotifyController
# Import actions
from .actions.MediaActions.PlayResumeAction import PlayResume
from .actions.MediaActions.NextSongAction import Next
from .actions.MediaActions.PreviousSongAction import Previous
from .actions.MediaActions.ShuffleAction import Shuffle
from .actions.MediaActions.RepeatAction import Repeat
from .actions.MediaActions.DeviceActions import SelectDevice
from .actions.MediaActions.VolumeActions import VolumeDown, VolumeUp

from loguru import logger as log
import gi
gi.require_version("Gtk" , "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk

class SpotifyForStreamController(PluginBase):
    def __init__(self):
        super().__init__()

        self.client_refresh_token_row = None
        self.login_button_row = None
        self.client_authorization_row = None
        self.client_secret_row = None
        self.client_id_row = None
        self.auth_controller = AuthController(self)
        self.controller = SpotifyController(self, self.auth_controller, 1)

        ## Register actions
        holder = ActionHolder(
            plugin_base = self,
            action_base = PlayResume,
            action_id = "de_outsider_Spotify::PlayPause", # Change this to your own plugin id
            action_name = "Play/Pause",
        )
        self.add_action_holder(holder)

        holder = ActionHolder(
            plugin_base=self,
            action_base=Next,
            action_id="de_outsider_Spotify::Next",  # Change this to your own plugin id
            action_name="Next Song",
        )
        self.add_action_holder(holder)

        holder = ActionHolder(
            plugin_base=self,
            action_base=Previous,
            action_id="de_outsider_Spotify::Previous",  # Change this to your own plugin id
            action_name="Previous Song",
        )
        self.add_action_holder(holder)

        holder = ActionHolder(
            plugin_base=self,
            action_base=Shuffle,
            action_id="de_outsider_Spotify::Shuffle",  # Change this to your own plugin id
            action_name="Toggle Shuffle Mode",
        )
        self.add_action_holder(holder)

        holder = ActionHolder(
            plugin_base=self,
            action_base=Repeat,
            action_id="de_outsider_Spotify::Repeat",  # Change this to your own plugin id
            action_name="Toggle Repeat Mode",
        )
        self.add_action_holder(holder)

        holder = ActionHolder(
            plugin_base=self,
            action_base=VolumeUp,
            action_id="de_outsider_Spotify::VolumeUp",  # Change this to your own plugin id
            action_name="Add 10 Percent to Playback Volume",
        )
        self.add_action_holder(holder)

        holder = ActionHolder(
            plugin_base=self,
            action_base=VolumeDown,
            action_id="de_outsider_Spotify::VolumeDown",  # Change this to your own plugin id
            action_name="Reduce Playback Volume by 10 Percent",
        )
        self.add_action_holder(holder)

        holder = ActionHolder(
            plugin_base=self,
            action_base=SelectDevice,
            action_id="de_outsider_Spotify::SelectDevice",  # Change this to your own plugin id
            action_name="Select Device from List",
        )
        self.add_action_holder(holder)

        # Register plugin
        self.register(
            plugin_name = "Spotify For StreamController",
            github_repo = "https://github.com/bamarc/SpotifyForStreamController",
            plugin_version = "0.2.0",
            app_version = "1.5.0-beta-10"
        )

    @property
    def get_controller(self) -> SpotifyController:
        return self.controller

    @property
    def get_auth_controller(self) -> AuthController:
        return self.auth_controller

    def get_settings_area(self):
        # Create a PreferencesPage and PreferencesGroup to hold the rows
        group = Adw.PreferencesGroup()
        config_rows = self.get_config_rows()
        for row in config_rows:
            group.add(row)
        return group

    def get_config_rows(self) -> list[Adw.PreferencesRow]:
        rows = []

        settings = self.get_settings()  # Get existing settings

        # String setting for client_id
        self.client_id_row = Adw.EntryRow(title="Client ID")
        client_id = settings.get("client_id")
        if client_id is not None:
            self.client_id_row.set_text(client_id)
        self.client_id_row.set_show_apply_button(True)
        self.client_id_row.connect("apply", self._on_client_id_entry_changed)
        rows.append(self.client_id_row)

        # Secret string setting for client_secret
        self.client_secret_row = Adw.PasswordEntryRow(title="Client Secret")
        secret = settings.get("client_secret")
        if secret is not None:
            self.client_secret_row.set_text(secret)
        self.client_secret_row.set_show_apply_button(True)
        self.client_secret_row.connect("apply", self._on_client_secret_entry_changed)
        rows.append(self.client_secret_row)

        self.login_button_row = Adw.ButtonRow(title="Login")
        self.login_button_row.connect("activated", self.on_login)
        rows.append(self.login_button_row)

        # Secret string setting for authorization_token
        self.client_authorization_row = Adw.PasswordEntryRow(title="Client Authorization")
        authorization = settings.get("client_authorization")
        if authorization is not None:
            self.client_authorization_row.set_text(authorization)
        self.client_authorization_row.set_show_apply_button(True)
        self.client_authorization_row.connect("apply", self._on_client_authorization_entry_changed)
        rows.append(self.client_authorization_row)

        # Secret string setting for refresh token
        self.client_refresh_token_row = Adw.PasswordEntryRow(title="Refresh Token")
        refresh_token = settings.get("client_refresh_token")
        if refresh_token is not None:
            self.client_refresh_token_row.set_text(refresh_token)
        self.client_refresh_token_row.set_show_apply_button(True)
        self.client_refresh_token_row.connect("apply", self._on_client_refresh_token_entry_changed)
        rows.append(self.client_refresh_token_row)

        return rows

    def handle_auth_code(self, code: str):
        settings = self.get_settings()  # Get existing settings
        settings["client_authorization"] = code
        del settings["client_refresh_token"]
        print(f"{self.plugin_name}: Client Secret entry has been modified.")
        self.on_save(settings)

    def on_login(self, _):
        controller = self.get_auth_controller
        controller.initiate_login_flow()

    def on_save(self, settings):
        self.set_settings(settings)

    def _on_client_id_entry_changed(self, entry_row):
        # Store client id
        settings = self.get_settings()  # Get existing settings
        client_id = entry_row.get_text()
        settings["client_id"] = client_id
        print(f"{self.plugin_name}: Client ID entry changed to: {client_id}")
        self.on_save(settings)

    def _on_client_secret_entry_changed(self, entry_row):
        #  Store client secret
        settings = self.get_settings()  # Get existing settings
        client_secret = entry_row.get_text()
        settings["client_secret"] = client_secret
        print(f"{self.plugin_name}: Client Secret entry has been modified.")
        self.on_save(settings)

    def _on_client_authorization_entry_changed(self, entry_row):
        #  Store client secret
        settings = self.get_settings()  # Get existing settings
        client_secret = entry_row.get_text()
        settings["client_authorization"] = client_secret
        print(f"{self.plugin_name}: Client Secret entry has been modified.")
        self.on_save(settings)

    def _on_client_refresh_token_entry_changed(self, entry_row):
        #  Store client secret
        settings = self.get_settings()  # Get existing settings
        client_secret = entry_row.get_text()
        settings["client_refresh_token"] = client_secret
        print(f"{self.plugin_name}: Client Refresh token entry has been modified.")
        self.on_save(settings)


