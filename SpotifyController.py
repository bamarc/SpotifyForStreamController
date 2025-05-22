import datetime
from http.client import responses

import requests
from urllib import parse
from loguru import logger as log

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('WebKit', '6.0') # Or WebKit2GTK for older GTK3/WebKit versions
from gi.repository import Gtk, Adw, WebKit, Gio, GLib

import globals as gl
import base64

class WebAuthWindow(Adw.Window):
    def __init__(self, initial_url, callback, **kwargs):
        super().__init__(**kwargs)
        self.initial_url = initial_url
        self.redirected_url = None
        self.callback = callback

        self.set_title("Web Login")
        self.set_default_size(600, 400)

        self.webview = WebKit.WebView()
        self.set_content(self.webview)

        # Connect to the 'load-changed' signal to detect URL changes
        self.webview.connect("load-changed", self._on_load_changed)
        # Connect to 'decide-policy' for more control (optional but good for redirects)
        self.webview.connect("decide-policy", self._on_decide_policy)

        self.webview.load_uri(self.initial_url)

    def _on_load_changed(self, webview, load_event):
        if load_event == WebKit.LoadEvent.FINISHED:
            current_uri = webview.get_uri()
            log.info(f"Load finished: {current_uri}")
            # You might have specific conditions to check here
            # if self.is_redirect_target(current_uri):
            #     self.redirected_url = current_uri
            #     print(f"Redirect detected (from load-changed): {self.redirected_url}")
            #     self.close_and_extract()

    def _on_decide_policy(self, webview, decision, decision_type):
        if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            nav_action = decision.get_navigation_action()
            uri = nav_action.get_request().get_uri()
            log.info(f"Navigating to: {uri}")

            # THIS IS WHERE YOU'LL LIKELY DETECT THE REDIRECT
            # Add your specific logic to identify the target redirect URL
            if self.is_redirect_target(uri):
                self.redirected_url = uri
                log.info(f"Redirect target reached: {self.redirected_url}")
                self.close_and_extract()
                decision.ignore() # Stop the navigation in the webview
                return True
        # Allow other decisions (e.g., new window, download)
        return False # Let the default handler manage it

    def is_redirect_target(self, url):
        # Replace this with your actual logic to identify the redirect.
        # For example, if your redirect URL starts with "myapp://callback"
        return url.startswith("https://stream-controller/callback") # Example

    def close_and_extract(self):
        log.info(f"Closing window. Extracted URL: {self.redirected_url}")
        code = self.redirected_url.split("https://stream-controller/callback?code=", 1)[1]
        log.info(f"Closing window. Extracted Code: {code}")
        self.close()
        # You can emit a signal here or call a callback with the extracted URL
        if code and self.callback:
            GLib.idle_add(self.callback, code)

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

class SpotifyController:
    def __init__(self, settings, plugin_base):
        self.token = None
        self.settings = settings
        self.plugin_base = plugin_base

    def login(self):
        url = "https://accounts.spotify.com/authorize?"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "response_type": "code",
            "client_id": f"{self.settings["client_id"]}",
            "redirect_uri": "https://stream-controller/callback",
            "scope": "user-read-playback-state user-modify-playback-state user-read-currently-playing"
        }
        encoded_data = parse.urlencode(data)
        log.info(f"url: {url}{encoded_data}")
        self.web_auth_window = WebAuthWindow(
            application=gl.app,
            initial_url=url+encoded_data,
            modal=True,
            callback=self.plugin_base.handle_auth_code
        )
        self.web_auth_window.present()

    def get_initial_token(self):
        secrets = f"{self.settings["client_id"]}:{self.settings["client_secret"]}"
        b64secrets = base64.b64encode(secrets.encode('utf-8')).decode('utf-8')
        log.info("secrets:" + b64secrets)
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
        log.info(f"Access Token: {access_token}")
        refresh_token = response.json().get("refresh_token")
        log.info(f"Refresh Token: {refresh_token}")
        self.settings["client_refresh_token"] = refresh_token
        self.plugin_base._on_save(self.settings)

        self.token = Token(tokenString=access_token, until=response.json().get("expires_in"))
        return self.token

    def refresh_token(self):
        secrets = f"{self.settings["client_id"]}:{self.settings["client_secret"]}"
        b64secrets = base64.b64encode(secrets.encode('utf-8')).decode('utf-8')
        log.info("secrets:" + b64secrets)
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
        log.info(f"Access Token: {access_token}")
        refresh_token = response.json().get("refresh_token")
        if refresh_token:
            log.info(f"Got new Refresh Token: {refresh_token}")
            self.settings["client_refresh_token"] = refresh_token
            self.plugin_base._on_save(self.settings)

        self.token = Token(tokenString=access_token, until=response.json().get("expires_in"))
        return self.token

    def get_or_refresh_token(self):
        refresh_token = self.settings.get("client_refresh_token")
        if self.token is None or not self.token.is_valid:
            if refresh_token is None:
                return self.get_initial_token().get_token_str
            else :
                return self.refresh_token().get_token_str
        else:
            return self.token.get_token_str

    def is_playing(self):
        url = "https://api.spotify.com/v1/me/player"
        headers = {
            "Authorization": f"Bearer {self.get_or_refresh_token()}"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        if response.status_code == 200:
            return response.json().get("is_playing")
        else:
            return None


    def pause(self):
        url = "https://api.spotify.com/v1/me/player/pause"
        headers = {
            "Authorization" : f"Bearer {self.get_or_refresh_token()}"
        }
        response = requests.put(url, headers=headers)

    def play(self):
        url = "https://api.spotify.com/v1/me/player/play"
        headers = {
            "Authorization": f"Bearer {self.get_or_refresh_token()}"
        }
        response = requests.put(url, headers=headers)

    def next(self):
        url = "https://api.spotify.com/v1/me/player/next"
        headers = {
            "Authorization": f"Bearer {self.get_or_refresh_token()}"
        }
        response = requests.post(url, headers=headers)

    def previous(self):
        url = "https://api.spotify.com/v1/me/player/previous"
        headers = {
            "Authorization": f"Bearer {self.get_or_refresh_token()}"
        }
        response = requests.post(url, headers=headers)

