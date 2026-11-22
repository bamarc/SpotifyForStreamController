import datetime
import base64
import inspect
import threading
import time  # For retry backoff
import random  # For jitter
import weakref
from dataclasses import dataclass
from functools import wraps
from typing import Callable, Optional, Dict, Any, List, Tuple, TypeVar, ParamSpec
from urllib import parse

import requests
from loguru import logger as log

from gi.repository import GLib

from .WebAuthWindow import WebAuthWindow
import globals as gl  # For gl.app

# --- Constants ---
SPOTIFY_ACCOUNTS_URL = "https://accounts.spotify.com"
SPOTIFY_API_URL = "https://api.spotify.com/v1"
REDIRECT_URI = "https://stream-controller/callback"  # Ensure this is registered in your Spotify App
DEFAULT_SCOPE = "user-read-playback-state user-modify-playback-state user-read-currently-playing"

TOKEN_ENDPOINT = f"{SPOTIFY_ACCOUNTS_URL}/api/token"
AUTHORIZE_ENDPOINT = f"{SPOTIFY_ACCOUNTS_URL}/authorize"

PLAYER_BASE_ENDPOINT = f"{SPOTIFY_API_URL}/me/player"
DEVICES_ENDPOINT = f"{PLAYER_BASE_ENDPOINT}/devices"
# ... (other specific API endpoints can be defined here if preferred over constructing them inline)

# --- Type Variables for Decorator ---
P = ParamSpec('P')  # For the parameters of the decorated function
R = TypeVar('R')  # For the return type of the decorated function


# --- Retry Decorator ---
def spotify_api_request_handler(
        max_retries: int = 3,
        initial_backoff: float = 1.0,
        max_backoff: float = 10.0,
        jitter_factor: float = 0.1
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator for Spotify API requests with retry logic, exponential backoff, and jitter.
    It expects the decorated function to return a requests.Response object if retry
    logic is to be applied. If a non-Response object is returned, it's passed through.
    It will call response.raise_for_status() and handle retries for Response objects.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            current_backoff = initial_backoff
            last_exception = None

            for attempt in range(max_retries):
                try:
                    response_or_value = func(*args, **kwargs)

                    if not isinstance(response_or_value, requests.Response):
                        # If the decorated function doesn't return a Response (e.g., early exit,
                        # or it's designed to return other data types),
                        # we shouldn't try to call raise_for_status or retry.
                        log.debug(
                            f"Function '{func.__name__}' did not return a requests.Response. Bypassing retry logic.")
                        return response_or_value

                    # At this point, response_or_value is a requests.Response object
                    response: requests.Response = response_or_value
                    response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
                    return response  # type: ignore # R might not strictly be requests.Response, but this path returns one.
                    # More advanced typing could use an overload or a conditional return type
                    # if R could be something other than what func returns.
                    # However, this is often acceptable given the isinstance check.

                except requests.exceptions.HTTPError as e:
                    # For 4xx client errors (except 429 Too Many Requests), don't retry.
                    # 401/403 might indicate token issues that retrying won't fix here.
                    # The calling code should handle token refresh based on these.
                    if e.response is not None and 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                        url = e.request.url if e.request is not None else e.response.url
                        log.warning(
                            f"Client error {e.response.status_code} for {url} in '{func.__name__}'. No retry. Body: {e.response.text[:200]}")
                        raise  # Re-raise to be handled by the caller
                    log.warning(
                        f"Request '{func.__name__}' failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {current_backoff:.2f}s.")
                    last_exception = e
                except requests.exceptions.RequestException as e:  # Covers ConnectionError, Timeout, etc.
                    log.warning(
                        f"Request '{func.__name__}' failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {current_backoff:.2f}s.")
                    last_exception = e

                if attempt < max_retries - 1:
                    jitter = random.uniform(-jitter_factor, jitter_factor) * current_backoff
                    time.sleep(current_backoff + jitter)
                    current_backoff = min(current_backoff * 2, max_backoff)  # Exponential backoff

            if last_exception:
                log.error(f"Request '{func.__name__}' failed after {max_retries} retries: {last_exception}")
                raise last_exception

            # This line should ideally not be reached if the decorated function always returns a value
            # or if an exception is always raised upon failure after retries.
            # It acts as a safeguard for unexpected control flow.
            raise RuntimeError(
                f"Decorator logic error in '{func.__name__}': function completed without returning a value or raising an exception after retries.")

        return wrapper

    return decorator

@dataclass
class Device:
    id: str
    is_active: bool
    is_private_session: bool
    is_restricted: bool
    name: str
    type: str
    volume_percent: int
    supports_volume: bool

# --- Token Class ---
class Token:
    def __init__(self, token_string: str, expires_in: int):
        self.token_string = token_string
        # expires_in is in seconds. Add a small buffer (e.g., 60s) to consider it expired earlier.
        buffer_seconds = 60
        self.expires_at = datetime.datetime.now() + datetime.timedelta(seconds=max(0, expires_in - buffer_seconds))
        log.debug(f"New token created, expires at {self.expires_at.isoformat()}")

    @property
    def is_valid(self) -> bool:
        return datetime.datetime.now() < self.expires_at

    @property
    def value(self) -> str:
        return self.token_string


# --- AuthController Class ---
class AuthController:
    def __init__(self, plugin_base: Any):  # Replace Any with actual plugin_base type
        self.access_token_obj: Optional[Token] = None
        self.plugin_base = plugin_base
        self._auth_window: Optional[WebAuthWindow] = None

    def _get_settings(self) -> Dict[str, Any]:
        return self.plugin_base.get_settings() or {}

    def _get_client_credentials(self) -> Tuple[Optional[str], Optional[str]]:
        settings = self._get_settings()
        return settings.get("client_id"), settings.get("client_secret")

    def _encode_basic_auth(self, client_id: str, client_secret: str) -> str:
        credentials = f"{client_id}:{client_secret}"
        return base64.b64encode(credentials.encode('utf-8')).decode('utf-8')

    @spotify_api_request_handler()
    def _request_token_from_spotify(self, data: Dict[str, str]) -> requests.Response:
        """Internal method to request an access token, decorated for retries."""
        client_id, client_secret = self._get_client_credentials()
        if not client_id or not client_secret:
            # This should ideally be caught before calling if possible,
            # but as a safeguard for the request itself:
            log.error("Client ID or Client Secret is missing. Cannot make token request.")
            # Return a dummy response or raise to prevent decorator from proceeding without valid request
            raise ValueError("Client ID or Client Secret is missing for token request")

        b64_creds = self._encode_basic_auth(client_id, client_secret)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {b64_creds}"
        }
        log.debug(f"Requesting token from {TOKEN_ENDPOINT} with grant_type: {data.get('grant_type')}")
        return requests.post(TOKEN_ENDPOINT, headers=headers, data=data, timeout=10)

    def _process_token_response(self, response_data: Dict[str, Any], grant_type: str) -> bool:
        access_token_str = response_data.get("access_token")
        expires_in = response_data.get("expires_in")

        if not access_token_str or not isinstance(expires_in, int):
            log.error(f"Access token or expires_in missing/invalid in {grant_type} response.")
            return False

        self.access_token_obj = Token(token_string=access_token_str, expires_in=expires_in)

        # Spotify may issue a new refresh token. It's guaranteed on auth_code grant.
        new_refresh_token = response_data.get("refresh_token")
        if new_refresh_token:
            settings = self._get_settings()
            settings["client_refresh_token"] = new_refresh_token
            log.info("New refresh token received and stored in settings.")
            self.plugin_base.on_save(settings)  # Persist changes

        log.info(f"Successfully obtained and processed new access token via {grant_type}.")
        return True

    def exchange_code_for_token(self, authorization_code: str) -> bool:
        """Exchanges an authorization code for an access token and refresh token."""
        if not authorization_code:
            log.error("Authorization code is missing. Cannot exchange for token.")
            return False

        client_id, _ = self._get_client_credentials()
        if not client_id:  # client_id not strictly needed for this grant_type in headers if using Basic Auth
            log.error("Client ID is missing in settings. Cannot exchange code for token.")
            return False

        data = {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": REDIRECT_URI,
            # "client_id": client_id, # Not needed in body if Basic Auth is used
        }
        try:
            response = self._request_token_from_spotify(data)
            return self._process_token_response(response.json(), "authorization_code")
        except requests.RequestException as e:
            log.error(f"Failed to exchange authorization code for token: {e}")
            if hasattr(e, 'response') and e.response is not None:
                log.error(f"Response details: Status {e.response.status_code}, Body: {e.response.text[:200]}")
        except ValueError as e:  # JSONDecodeError or other ValueErrors
            log.error(f"Error processing token response (auth code grant): {e}")
        return False

    def refresh_access_token(self) -> bool:
        """Refreshes an expired access token using a refresh token."""
        current_refresh_token = self._get_settings().get("client_refresh_token")
        client_id, _ = self._get_client_credentials()  # client_id is required for refresh token grant by Spotify

        if not current_refresh_token:
            log.warning("Refresh token is missing. Cannot refresh access token.")
            return False
        if not client_id:
            log.error("Client ID is missing. Cannot refresh access token (required in request body).")
            return False

        data = {
            "grant_type": "refresh_token",
            "refresh_token": current_refresh_token,
            "client_id": client_id,  # Spotify requires client_id in the body for refresh token grant
        }
        log.info("Attempting to refresh access token...")
        try:
            response = self._request_token_from_spotify(data)
            return self._process_token_response(response.json(), "refresh_token")
        except requests.RequestException as e:
            log.error(f"Failed to refresh access token: {e}")
            if hasattr(e, 'response') and e.response is not None:
                log.error(f"Response details: Status {e.response.status_code}, Body: {e.response.text[:200]}")
                # If refresh token is invalid (e.g., 400 Bad Request with specific error), clear it
                if e.response.status_code == 400:
                    error_payload = e.response.json()
                    if error_payload.get("error") == "invalid_grant":
                        log.warning("Refresh token is invalid. Clearing it from settings.")
                        settings = self._get_settings()
                        if settings.get("client_refresh_token") == current_refresh_token:
                            settings.pop("client_refresh_token", None)
                            self.plugin_base.on_save(settings)
                        # Potentially trigger a new full login flow here if appropriate for the app
        except ValueError as e:  # JSONDecodeError
            log.error(f"Error processing token response (refresh grant): {e}")
        return False

    def has_token_or_refresh_token(self) -> bool:
        return bool(
            (self.access_token_obj and self.access_token_obj.is_valid)
            or self._get_settings().get("client_refresh_token")
        )

    def get_valid_token_string(self) -> Optional[str]:
        """
        Provides a valid access token string.
        Checks current token, tries to refresh if invalid/missing.
        Does NOT handle initial code exchange; that's triggered by plugin_base.handle_auth_code -> exchange_code_for_token.
        """
        if self.access_token_obj and self.access_token_obj.is_valid:
            return self.access_token_obj.value

        log.info("Access token is invalid or missing. Attempting to refresh.")
        if self.refresh_access_token():  # This updates self.access_token_obj on success
            if self.access_token_obj and self.access_token_obj.is_valid:  # Double check after refresh
                return self.access_token_obj.value
            else:
                log.error("Token refresh reported success, but token object is still invalid or None.")
        else:
            log.warning("Failed to refresh token. A new login flow might be required.")

        log.error("Unable to obtain a valid access token via refresh.")
        return None

    def initiate_login_flow(self):
        """Initiates the Spotify OAuth authorization flow via WebAuthWindow."""
        client_id = self._get_settings().get("client_id")
        if not client_id:
            log.error("Client ID is missing in settings. Cannot initiate login.")
            return

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": DEFAULT_SCOPE,
            # Force Spotify consent screen so cached WebKit sessions don't auto-redirect and close immediately.
            "show_dialog": "true",
        }
        encoded_params = parse.urlencode(params)

        if not gl.app:  # Ensure gl.app is a valid Gtk.Application or Adw.Application instance
            log.error("Gtk.Application instance (gl.app) not available for WebAuthWindow.")
            return

        old_window = self._auth_window
        if old_window is not None:
            self._auth_window = None
            old_window.close()

        parent = gl.app.get_active_window()
        if parent is old_window:
            parent = None

        web_auth_window = WebAuthWindow(
            application=gl.app,
            transient_for=parent,
            initial_url=f"{AUTHORIZE_ENDPOINT}?{encoded_params}",
            modal=parent is not None,
            callback=self.plugin_base.handle_auth_code
        )
        web_auth_window.connect("destroy", self._on_auth_window_destroyed)
        self._auth_window = web_auth_window
        web_auth_window.present()
        log.info("WebAuthWindow presented for Spotify login.")

    def _on_auth_window_destroyed(self, window):
        if self._auth_window is window:
            self._auth_window = None


# --- SpotifyController Class ---
class SpotifyController:
    def __init__(self, plugin_base: Any, auth_controller: AuthController, update_interval_seconds: int = 2):
        self.plugin_base = plugin_base
        self.auth_controller = auth_controller  # Injected AuthController instance
        self.update_callbacks: List[Callable[[Optional[Dict[str, Any]]], None]] = []
        self.latest_playback_state: Optional[Dict[str, Any]] = None

        self._update_interval = update_interval_seconds
        self._polling_thread: Optional[threading.Thread] = None
        self._stop_polling_event = threading.Event()

        # Consider auto-starting polling or requiring an explicit start
        self.start_polling_updates()

    @spotify_api_request_handler(max_retries=2, initial_backoff=0.5)  # Shorter retries for playback state
    def _make_api_request(self, method: str, endpoint_url: str, **kwargs) -> Optional[requests.Response]:
        """Helper to make authenticated requests to Spotify API, decorated for retries."""
        token_str = self.auth_controller.get_valid_token_string()
        if not token_str:
            log.warning(f"Cannot make API request to {endpoint_url}: No valid token.")
            return None  # Propagate that token is unavailable

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token_str}"

        log.trace(f"Making Spotify API request: {method} {endpoint_url}")
        response = requests.request(method, endpoint_url, headers=headers, timeout=10, **kwargs)
        if response.status_code in (401, 403):
            log.warning(
                f"Authentication/Authorization error ({response.status_code}) calling {endpoint_url}. Token might be revoked.")
            # Invalidate before the retry decorator calls raise_for_status().
            self.auth_controller.access_token_obj = None
        return response

    def get_playback_state(self) -> Optional[Dict[str, Any]]:
        """Fetches the current playback state from Spotify."""
        try:
            response = self._make_api_request("GET", PLAYER_BASE_ENDPOINT)
            if response:
                if response.status_code == 200:  # State returned
                    return response.json()
                elif response.status_code == 204:  # No active device / content
                    log.info("No active Spotify device or content playing (204).")
                    return None  # Represent as no state (e.g., player closed or idle)
                # Other status codes are handled by raise_for_status in decorator
            return None  # If _make_api_request returned None (e.g. no token)
        except requests.RequestException as e:  # Catch errors from _make_api_request
            log.error(f"Error fetching playback state: {e}")
        except ValueError:  # JSONDecodeError
            log.error("Error decoding JSON from get_playback_state response.")
        return None

    def _get_current_or_fresh_state(self, provided_state: Optional[Dict]) -> Optional[Dict]:
        """Returns provided_state, latest_playback_state, or fetches new state."""
        if provided_state:
            return provided_state
        if self.latest_playback_state:  # Use cached state if available
            return self.latest_playback_state
        log.debug("No cached or provided state, fetching fresh playback state.")
        return self.get_playback_state()  # Fetch fresh state as last resort

    def is_playing(self, state: Optional[Dict] = None) -> Optional[bool]:
        current_state = self._get_current_or_fresh_state(state)
        return current_state.get("is_playing") if current_state else None

    def get_playback_art_url(self, state: Optional[Dict] = None) -> Optional[str]:
        current_state = self._get_current_or_fresh_state(state)
        if not current_state: return None

        item = current_state.get("item")
        if not isinstance(item, dict): return None

        album = item.get("album")
        if not isinstance(album, dict): return None

        images = album.get("images")
        if not isinstance(images, list) or not images: return None

        image_obj = images[0]  # Assuming the first image (often largest or a good default)
        return image_obj.get("url") if isinstance(image_obj, dict) else None

    # --- Playback Control Methods --- (Return True on success, False on failure/error)
    def _control_playback(self, method: str, endpoint: str, **kwargs) -> bool:
        try:
            response = self._make_api_request(method, endpoint, **kwargs)
            return response is not None and 200 <= response.status_code < 300
        except requests.RequestException as e:
            log.error(f"Playback control command {method} {endpoint} failed: {e}")
            return False

    def pause(self) -> bool:
        return self._control_playback("PUT", f"{PLAYER_BASE_ENDPOINT}/pause")

    def play(self) -> bool:
        # Spotify might need a device_id if no active device.
        # For simplicity, this assumes a device is active or Spotify handles it.
        return self._control_playback("PUT", f"{PLAYER_BASE_ENDPOINT}/play")

    def next_track(self) -> bool:
        return self._control_playback("POST", f"{PLAYER_BASE_ENDPOINT}/next")

    def previous_track(self) -> bool:
        return self._control_playback("POST", f"{PLAYER_BASE_ENDPOINT}/previous")

    def toggle_shuffle(self) -> Optional[bool]:
        current_shuffle_state = self.get_shuffle_state(self.latest_playback_state)  # Try cached first
        if current_shuffle_state is None:  # Still None, try a fresh API call
            current_shuffle_state = self.get_shuffle_state()

        if current_shuffle_state is None:
            log.warning("Could not determine current shuffle state to toggle.")
            return None

        new_target_state_bool = not current_shuffle_state
        success = self._control_playback("PUT", f"{PLAYER_BASE_ENDPOINT}/shuffle",
                                         params={"state": str(new_target_state_bool).lower()})
        return new_target_state_bool if success else None

    def set_repeat_state(self, target_repeat_state: str) -> bool:  # "track", "context", or "off"
        if target_repeat_state not in ["track", "context", "off"]:
            log.error(f"Invalid repeat state: {target_repeat_state}.")
            return False
        return self._control_playback("PUT", f"{PLAYER_BASE_ENDPOINT}/repeat", params={"state": target_repeat_state})

    def set_volume(self, volume_percent: int) -> bool:
        limited_volume = min(max(volume_percent, 0), 100)
        return self._control_playback("PUT", f"{PLAYER_BASE_ENDPOINT}/volume",
                                      params={"volume_percent": limited_volume})

    def get_shuffle_state(self, state: Optional[Dict] = None) -> Optional[bool]:
        current_state = self._get_current_or_fresh_state(state)
        return current_state.get("shuffle_state") if current_state else None

    def get_repeat_state(self, state: Optional[Dict] = None) -> Optional[str]:
        current_state = self._get_current_or_fresh_state(state)
        return current_state.get("repeat_state") if current_state else None  # "track", "context", or "off"

    def get_volume(self, state: Optional[Dict] = None) -> Optional[int]:
        current_state = self._get_current_or_fresh_state(state)
        if current_state:
            device = current_state.get("device")
            if isinstance(device, dict):
                return device.get("volume_percent")
        return None

    def _live_callbacks(self) -> List[Callable[[Optional[Dict[str, Any]]], None]]:
        live = []
        alive_refs = []
        for ref in list(self.update_callbacks):
            cb = ref() if isinstance(ref, weakref.ReferenceType) else ref
            if cb is not None:
                live.append(cb)
                alive_refs.append(ref)
        self.update_callbacks = alive_refs
        return live

    # --- Polling Logic ---
    def _perform_update_and_notify(self):
        callbacks = self._live_callbacks()
        if not callbacks or not self.auth_controller.has_token_or_refresh_token():
            return

        log.trace("Polling for Spotify playback state update...")
        new_state = self.get_playback_state()  # This handles its own token needs and request errors

        changed = False
        if new_state is not None:  # We got a valid state (could be playing or not, but device is active)
            prev = self.latest_playback_state
            new_item = new_state.get("item") or {}
            prev_item = (prev.get("item") or {}) if prev else {}
            new_device = new_state.get("device") or {}
            prev_device = (prev.get("device") or {}) if prev else {}

            if prev is None or \
                    new_item.get("id") != prev_item.get("id") or \
                    new_state.get("is_playing") != prev.get("is_playing") or \
                    new_state.get("shuffle_state") != prev.get("shuffle_state") or \
                    new_state.get("repeat_state") != prev.get("repeat_state") or \
                    new_device.get("id") != prev_device.get("id") or \
                    new_device.get("volume_percent") != prev_device.get("volume_percent"):
                log.info("Spotify playback state changed.")
                self.latest_playback_state = new_state
                changed = True
            else:
                log.trace("No significant change in active playback state.")
        elif self.latest_playback_state is not None:  # Previously had state, now new_state is None (e.g. player closed/inactive)
            log.info("Spotify playback became inactive or unavailable (was previously active).")
            self.latest_playback_state = None  # Update to reflect inactivity
            changed = True
        # If both new_state and latest_playback_state are None, no change.

        if changed:
            for callback in callbacks:
                name = getattr(callback, '__name__', repr(callback))
                try:
                    # Ensure UI updates happen on the main GTK thread
                    GLib.idle_add(callback, self.latest_playback_state)  # Pass the new state (can be None)
                except Exception as e:
                    log.error(f"Error scheduling/executing callback {name} via GLib.idle_add: {e}")

    def _polling_loop(self):
        log.info(f"Spotify polling loop started. Interval: {self._update_interval}s.")
        while not self._stop_polling_event.is_set():
            start_time = time.monotonic()
            try:
                self._perform_update_and_notify()
            except Exception as e:
                log.error(f"Unexpected error in Spotify polling loop: {e}")
            elapsed_time = time.monotonic() - start_time

            wait_time = self._update_interval - elapsed_time
            if wait_time > 0:
                if self._stop_polling_event.wait(wait_time):  # True if event set during wait
                    break
                    # If processing took longer than interval, loop immediately (or with minimal delay)
            # This ensures we don't drift too far if API calls are slow.
        log.info("Spotify polling loop stopped.")

    def start_polling_updates(self):
        if self._polling_thread and self._polling_thread.is_alive():
            log.info("Polling thread is already running.")
            return
        self._stop_polling_event.clear()
        self._polling_thread = threading.Thread(target=self._polling_loop, daemon=True, name="SpotifyPollingThread")
        self._polling_thread.start()

    def stop_polling_updates(self):
        if not self._polling_thread or not self._polling_thread.is_alive():
            log.info("Polling thread not running or already stopped.")
            return
        log.info("Stopping Spotify polling updates...")
        self._stop_polling_event.set()
        # Give the thread a bit more time than the interval to finish its current cycle + wait
        self._polling_thread.join(timeout=self._update_interval + 2.0)
        if self._polling_thread.is_alive():
            log.warning("Polling thread did not stop in time.")
        self._polling_thread = None
        log.info("Polling stopped.")

    def register_update_callback(self, callback: Callable[[Optional[Dict[str, Any]]], None]):
        name = getattr(callback, '__name__', repr(callback))
        if not callable(callback):
            log.error(f"Attempted to register non-callable object as callback: {name}")
            return
        if callback not in self._live_callbacks():
            ref = weakref.WeakMethod(callback) if inspect.ismethod(callback) else weakref.ref(callback)
            self.update_callbacks.append(ref)
            log.info(f"Callback {name} registered.")
            if self.latest_playback_state is not None:
                GLib.idle_add(callback, self.latest_playback_state)
        else:
            log.info(f"Callback {name} already registered.")

    def unregister_update_callback(self, callback: Callable[[Optional[Dict[str, Any]]], None]):
        name = getattr(callback, '__name__', repr(callback))
        kept = []
        removed = False
        for ref in list(self.update_callbacks):
            cb = ref() if isinstance(ref, weakref.ReferenceType) else ref
            if cb is None:
                continue
            if cb == callback:
                removed = True
                continue
            kept.append(ref)
        self.update_callbacks = kept
        if removed:
            log.info(f"Callback {name} unregistered.")
        else:
            log.warning(f"Callback {name} not found for unregistration.")

    def get_raw_playback_devices(self)-> Optional[Dict[str, Any]]:
        """Fetches the current playback state from Spotify."""
        try:
            response = self._make_api_request("GET", DEVICES_ENDPOINT)
            if response:
                if response.status_code == 200:  # State returned
                    return response.json()
                # Other status codes are handled by raise_for_status in decorator
            return None  # If _make_api_request returned None (e.g. no token)
        except requests.RequestException as e:  # Catch errors from _make_api_request
            log.error(f"Error fetching device list: {e}")
        except ValueError:  # JSONDecodeError
            log.error("Error decoding JSON from get_playback_state response.")
        return None

    def get_playback_devices(self) -> Optional[List[Device]]:
        """Fetches and converts playback devices into a list of Device objects."""
        raw_devices_data = self.get_raw_playback_devices()

        if not raw_devices_data or "devices" not in raw_devices_data:
            log.info("No device data found or 'devices' key missing in response.")
            return None  # Or return [] if you prefer an empty list for no devices

        devices_list = []
        for device_dict in raw_devices_data["devices"]:
            try:
                # Convert the 'type' string to DeviceType enum
                # The Spotify API often uses TitleCase for device types,
                # so ensure your from_string or direct enum conversion handles this (e.g., .lower())
                device_type_str = device_dict.get("type", "unknown")  # Default to "unknown" if missing
                #device_type_enum = DeviceType.from_string(device_type_str)

                # Create the Device dataclass instance
                # Using .get() for keys that might be missing to avoid KeyErrors
                # or ensure your API contract guarantees their presence.
                device_obj = Device(
                    id=device_dict["id"],  # Assuming 'id' is always present
                    is_active=device_dict.get("is_active", False),
                    is_private_session=device_dict.get("is_private_session", False),
                    is_restricted=device_dict.get("is_restricted", False),
                    name=device_dict.get("name", "Unknown Device"),
                    type=device_type_str,
                    volume_percent=device_dict.get("volume_percent"),  # Handles if volume_percent is null
                    supports_volume=device_dict.get("supports_volume", False)
                )
                devices_list.append(device_obj)
            except KeyError as e:
                log.error(f"Missing key {e} in device data: {device_dict}")
            except Exception as e:  # Catch any other unexpected error during conversion
                log.error(f"Error converting device data to Device object: {e}. Data: {device_dict}")

        return devices_list

    def set_playback_device(self, device) -> bool:
        try:
            response = self._make_api_request("PUT", PLAYER_BASE_ENDPOINT,
                                              json={"device_ids": [device.id]})
            return response is not None and 200 <= response.status_code < 300
        except requests.RequestException as e:
            log.error(f"Setting playback device failed: {e}")
            return False


