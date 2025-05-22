import datetime
from http.client import responses

import requests
from urllib import parse
from loguru import logger as log

import gi

from .WebAuthWindow import WebAuthWindow

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('WebKit', '6.0') # Or WebKit2GTK for older GTK3/WebKit versions
from gi.repository import Gtk, Adw, WebKit, Gio, GLib

import globals as gl
import base64


class Token:
    def __init__(self, tokenString: str, until:int):
        self.token = tokenString
        self.until = datetime.datetime.now() + datetime.timedelta(seconds=until)

    @property
    def is_valid(self):
        return True if datetime.datetime.now() < self.until else False

    @property
    def get_token_str(self):
        return self.token

class AuthController:
    def __init__(self, plugin_base):
        self.access_token = None
        self.plugin_base = plugin_base
        self.settings = plugin_base.get_settings()

    def login(self):
        url = "https://accounts.spotify.com/authorize?"
        data = {
            "response_type": "code",
            "client_id": f"{self.settings["client_id"]}",
            "redirect_uri": "https://stream-controller/callback",
            "scope": "user-read-playback-state user-modify-playback-state user-read-currently-playing"
        }
        encoded_data = parse.urlencode(data)
        web_auth_window = WebAuthWindow(
            application=gl.app,
            initial_url=url+encoded_data,
            modal=True,
            callback=self.plugin_base.handle_auth_code
        )
        web_auth_window.present()

    def get_initial_token(self):
        secrets = f"{self.settings["client_id"]}:{self.settings["client_secret"]}"
        b64secrets = base64.b64encode(secrets.encode('utf-8')).decode('utf-8')
        url = "https://accounts.spotify.com/api/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {b64secrets}"
        }
        data = {
            "code": f"{self.settings["client_authorization"]}",
            "redirect_uri": "https://stream-controller/callback",
            "grant_type": "authorization_code",
            "scope": "user-read-playback-state user-modify-playback-state user-read-currently-playing"
        }
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        access_token =  response.json().get("access_token")
        refresh_token = response.json().get("refresh_token")
        self.settings["client_refresh_token"] = refresh_token
        self.plugin_base.on_save(self.settings)

        self.access_token = Token(tokenString=access_token, until=response.json().get("expires_in"))
        return self.access_token

    def refresh_token(self):
        secrets = f"{self.settings["client_id"]}:{self.settings["client_secret"]}"
        b64secrets = base64.b64encode(secrets.encode('utf-8')).decode('utf-8')
        url = "https://accounts.spotify.com/api/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {b64secrets}"
        }
        data = {
            "grant_type": "refresh_token",
            "refresh_token": f"{self.settings["client_refresh_token"]}",
            "client_id": f"{self.settings["client_id"]}",
        }
        log.info(f"Refreshing token with url [{url}] + headers [{headers}] + data [{data}]")
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        access_token =  response.json().get("access_token")
        refresh_token = response.json().get("refresh_token")
        if refresh_token:
            log.info(f"Got new Refresh Token")
            self.settings["client_refresh_token"] = refresh_token
            self.plugin_base.on_save(self.settings)

        self.access_token = Token(tokenString=access_token, until=response.json().get("expires_in"))
        return self.access_token

    def get_or_refresh_token(self):
        refresh_token = self.settings.get("client_refresh_token")
        if self.access_token is None or not self.access_token.is_valid:
            if refresh_token is None:
                return self.get_initial_token().get_token_str
            else :
                return self.refresh_token().get_token_str
        else:
            return self.access_token.get_token_str

class SpotifyController:
    def __init__(self, plugin_base):
        self.token = None
        self.plugin_base = plugin_base
        self.auth_controller = AuthController(plugin_base)

    def login(self):
        self.auth_controller.login()

    def is_playing(self):
        state = self.get_playback_state()
        if state is not None:
            return state.get("is_playing")
        else:
            return None

    def pause(self) -> bool:
        url = "https://api.spotify.com/v1/me/player/pause"
        headers = {
            "Authorization" : f"Bearer {self.auth_controller.get_or_refresh_token()}"
        }
        response = requests.put(url, headers=headers)
        return  self.is_playing()

    def play(self) -> bool:
        url = "https://api.spotify.com/v1/me/player/play"
        headers = {
            "Authorization": f"Bearer {self.auth_controller.get_or_refresh_token()}"
        }
        response = requests.put(url, headers=headers)
        return self.is_playing()

    def next(self):
        url = "https://api.spotify.com/v1/me/player/next"
        headers = {
            "Authorization": f"Bearer {self.auth_controller.get_or_refresh_token()}"
        }
        response = requests.post(url, headers=headers)

    def previous(self):
        url = "https://api.spotify.com/v1/me/player/previous"
        headers = {
            "Authorization": f"Bearer {self.auth_controller.get_or_refresh_token()}"
        }
        response = requests.post(url, headers=headers)

    def get_playback_state(self):
        url = "https://api.spotify.com/v1/me/player"
        headers = {
            "Authorization": f"Bearer {self.auth_controller.get_or_refresh_token()}"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

    def get_shuffle_state(self):
        state = self.get_playback_state()
        if state:
            return state.get("shuffle_state")
        else:
            return None

    def shuffle(self) -> bool:
        try:
            shuffle_state = self.get_shuffle_state()
            if shuffle_state is None:
                pass
            url = "https://api.spotify.com/v1/me/player/shuffle"
            headers = {
                "Authorization": f"Bearer {self.auth_controller.get_or_refresh_token()}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            params = {
                "state": "false" if shuffle_state else "true"
            }
            response = requests.put(url, headers=headers, params=params)
            response.raise_for_status()
            return False if shuffle_state else True
        except Exception as e:
            log.error(e)

    def get_volume(self):
        state = self.get_playback_state()
        if state is None:
            log.warn("Could not retrieve Volume, setting to a sane default")
            return 10
        return state.get("device").get("volume_percent")

    def set_volume(self, volume : int):
        limited_volume = min(max(volume, 0), 100)
        url = "https://api.spotify.com/v1/me/player/volume"
        headers = {
            "Authorization": f"Bearer {self.auth_controller.get_or_refresh_token()}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        params = {
            "volume_percent": limited_volume
        }
        response = requests.put(url, headers=headers, params=params)
        response.raise_for_status()
