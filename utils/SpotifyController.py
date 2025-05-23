import datetime
from http.client import responses
from typing import Any

import requests
import threading
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
        client_id = self.settings.get("client_id")
        client_secret = self.settings.get("client_secret")
        client_authorization = self.settings.get("client_authorization")
        if client_id is None or client_secret is None or client_authorization is None:
            log.warn("Necessary secrets are missing, please trigger check config and trigger login to continue")
            return None

        secrets = f"{client_id}:{client_secret}"
        b64secrets = base64.b64encode(secrets.encode('utf-8')).decode('utf-8')
        url = "https://accounts.spotify.com/api/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {b64secrets}"
        }
        data = {
            "code": f"{client_authorization}",
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
    def __init__(self, plugin_base, update_interval_seconds=1):
        self.token = None
        self.plugin_base = plugin_base
        self.auth_controller = AuthController(plugin_base)
        self.update_callbacks = []
        self.latest_playback_state = None

        self._update_interval = update_interval_seconds
        self._polling_thread = None
        self._stop_polling_event = threading.Event()

        self.start_polling_updates()

    def login(self):
        self.auth_controller.login()

    def is_playing(self, state=None):
        if state is None:
            state = self.get_playback_state()
        if state is not None:
            return state.get("is_playing")
        else:
            return None

    def pause(self) -> bool:
        token = self.auth_controller.get_or_refresh_token()
        if token is None:
            log.info("Got no token, aborting operation")
            return False

        url = "https://api.spotify.com/v1/me/player/pause"
        headers = {
            "Authorization" : f"Bearer {token}"
        }
        response = requests.put(url, headers=headers)
        return  self.is_playing()

    def play(self) -> bool:
        token = self.auth_controller.get_or_refresh_token()
        if token is None:
            log.info("Got no token, aborting operation")
            return False

        url = "https://api.spotify.com/v1/me/player/play"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        response = requests.put(url, headers=headers)
        return self.is_playing()

    def next(self):
        token = self.auth_controller.get_or_refresh_token()
        if token is None:
            log.info("Got no token, aborting operation")
            return

        url = "https://api.spotify.com/v1/me/player/next"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        response = requests.post(url, headers=headers)

    def previous(self):
        token = self.auth_controller.get_or_refresh_token()
        if token is None:
            log.info("Got no token, aborting operation")
            return

        url = "https://api.spotify.com/v1/me/player/previous"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        response = requests.post(url, headers=headers)

    def get_playback_state(self):
        token = self.auth_controller.get_or_refresh_token()
        if token is None:
            log.info("Got no token, aborting operation")
            return None
        url = "https://api.spotify.com/v1/me/player"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        if response.status_code == 200:
            return response.json()
        else:
            return None

    def get_playback_art(self) -> str | None:
        state = self.get_playback_state()
        if state:
            # try to get playback item
            playback_item = state.get("item")
            if playback_item:
                #get album
                album_image_url = playback_item.get("album").get("images")[0].get("url")
                return album_image_url
        return None


    def get_shuffle_state(self, state=None):
        if state is None:
            state = self.get_playback_state()
        if state:
            return state.get("shuffle_state")
        else:
            return None

    def switch_shuffle(self) -> bool | None:
        try:
            shuffle_state = self.get_shuffle_state()
            token = self.auth_controller.get_or_refresh_token()
            if shuffle_state is None:
                return None
            if token is None:
                log.info("Got no token, aborting operation")
                return None
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            url = "https://api.spotify.com/v1/me/player/shuffle"
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

    def _perform_update_and_notify(self):
        """
        Fetches the latest playback state and notifies all registered callbacks.
        """
        log.trace("Performing update and notifying callbacks...")
        try:
            token = self.auth_controller.get_or_refresh_token()
            if token is None:
                return

            new_state = self.get_playback_state()
            if new_state and self.latest_playback_state is None:
                log.info("got new state")
                self.latest_playback_state = new_state  # Update stored state
                for callback in self.update_callbacks:
                    try:
                        callback(self.latest_playback_state)  # Pass the new state to the callback
                    except Exception as e:
                        log.error(f"Error executing callback {callback.__name__}: {e}")
            elif new_state and self.latest_playback_state and new_state.get("timestamp") != self.latest_playback_state.get("timestamp"):
                log.info("got new state")
                self.latest_playback_state = new_state # Update stored state
                for callback in self.update_callbacks:
                    try:
                        callback(self.latest_playback_state) # Pass the new state to the callback
                    except Exception as e:
                        log.error(f"Error executing callback {callback.__name__}: {e}")
            else:
                log.trace("No new state received or error fetching state.")

        except Exception as e:
            log.error(f"Error during _perform_update_and_notify: {e}")

    def _polling_loop(self):
        """
        The main loop for the polling thread.
        """
        while not self._stop_polling_event.is_set():
            self._perform_update_and_notify()
            self._stop_polling_event.wait(self._update_interval)
        log.info("Spotify polling loop stopped.")

    def start_polling_updates(self):
        """
        Starts the background thread to periodically fetch updates.
        """
        if self._polling_thread is None or not self._polling_thread.is_alive():
            self._stop_polling_event.clear()
            self._polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
            # daemon=True means the thread will exit when the main program exits
            self._polling_thread.start()
            log.info(f"Spotify polling updates started with interval: {self._update_interval}s")
        else:
            log.info("Polling thread is already running.")

    def stop_polling_updates(self):
        """
        Signals the polling thread to stop.
        """
        if self._polling_thread and self._polling_thread.is_alive():
            log.info("Stopping Spotify polling updates...")
            self._stop_polling_event.set()
            self._polling_thread.join(timeout=self._update_interval + 1) # Wait for the thread to finish
            if self._polling_thread.is_alive():
                log.warning("Polling thread did not stop in time.")
            self._polling_thread = None
        else:
            log.info("Polling thread is not running or already stopped.")

    def register_update_callback(self, callback):
        if callback not in self.update_callbacks:
            self.update_callbacks.append(callback)
            log.info(f"Callback {callback.__name__} registered.")
        else:
            log.info(f"Callback {callback.__name__} already registered.")

    def unregister_update_callback(self, callback):
        try:
            self.update_callbacks.remove(callback)
            log.info(f"Callback {callback.__name__} unregistered.")
        except ValueError:
            log.warning(f"Callback {callback.__name__} not found for unregistration.")

    def set_repeat(self, new_state):
        try:
            shuffle_state = self.get_shuffle_state()
            token = self.auth_controller.get_or_refresh_token()
            if shuffle_state is None:
                return
            if token is None:
                log.info("Got no token, aborting operation")
                return
            url = "https://api.spotify.com/v1/me/player/repeat"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            params = {
                "state": new_state
            }
            response = requests.put(url, headers=headers, params=params)
            response.raise_for_status()
        except Exception as e:
            log.error(e)

    def get_repeat_state(self, state=None):
        if state is None:
            state = self.get_playback_state()
        if state:
            return state.get("repeat_state")
        else:
            return None

