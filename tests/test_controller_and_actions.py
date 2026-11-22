import gc
import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_modules():
    pkg_name = "spotify_audit_testpkg"
    for name in list(sys.modules):
        if name == pkg_name or name.startswith(pkg_name + "."):
            del sys.modules[name]

    if "loguru" not in sys.modules:
        try:
            import loguru  # noqa: F401
        except ImportError:
            loguru_mod = types.ModuleType("loguru")
            loguru_mod.logger = MagicMock()
            sys.modules["loguru"] = loguru_mod

    src_mod = types.ModuleType("src")
    backend_mod = types.ModuleType("src.backend")
    pm_mod = types.ModuleType("src.backend.PluginManager")
    ab_mod = types.ModuleType("src.backend.PluginManager.ActionBase")

    class FakeActionBase:
        def __init__(self, plugin_base):
            self.plugin_base = plugin_base
            self.media_calls = []

        def set_media(self, **kwargs):
            self.media_calls.append(kwargs)

    ab_mod.ActionBase = FakeActionBase

    globals_mod = types.ModuleType("globals")
    globals_mod.app = MagicMock()

    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(REPO_ROOT)]
    utils_pkg = types.ModuleType(f"{pkg_name}.utils")
    utils_pkg.__path__ = [str(REPO_ROOT / "utils")]
    actions_pkg = types.ModuleType(f"{pkg_name}.actions")
    actions_pkg.__path__ = [str(REPO_ROOT / "actions")]
    media_pkg = types.ModuleType(f"{pkg_name}.actions.MediaActions")
    media_pkg.__path__ = [str(REPO_ROOT / "actions" / "MediaActions")]

    sys.modules.update({
        "src": src_mod,
        "src.backend": backend_mod,
        "src.backend.PluginManager": pm_mod,
        "src.backend.PluginManager.ActionBase": ab_mod,
        "globals": globals_mod,
        pkg_name: pkg,
        f"{pkg_name}.utils": utils_pkg,
        f"{pkg_name}.actions": actions_pkg,
        f"{pkg_name}.actions.MediaActions": media_pkg,
    })

    def load(mod_name, rel_path):
        spec = importlib.util.spec_from_file_location(mod_name, REPO_ROOT / rel_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod

    web_auth = load(f"{pkg_name}.utils.WebAuthWindow", "utils/WebAuthWindow.py")
    spotify_ctrl = load(f"{pkg_name}.utils.SpotifyController", "utils/SpotifyController.py")
    repeat_mod = load(f"{pkg_name}.actions.MediaActions.RepeatAction", "actions/MediaActions/RepeatAction.py")
    volume_mod = load(f"{pkg_name}.actions.MediaActions.VolumeActions", "actions/MediaActions/VolumeActions.py")
    device_mod = load(f"{pkg_name}.actions.MediaActions.DeviceActions", "actions/MediaActions/DeviceActions.py")
    play_mod = load(f"{pkg_name}.actions.MediaActions.PlayResumeAction", "actions/MediaActions/PlayResumeAction.py")
    shuffle_mod = load(f"{pkg_name}.actions.MediaActions.ShuffleAction", "actions/MediaActions/ShuffleAction.py")
    return types.SimpleNamespace(
        web_auth=web_auth,
        spotify_ctrl=spotify_ctrl,
        repeat_mod=repeat_mod,
        volume_mod=volume_mod,
        device_mod=device_mod,
        play_mod=play_mod,
        shuffle_mod=shuffle_mod,
        gl=globals_mod,
    )


class ControllerAndActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mods = _load_modules()

    def _make_controller(self, settings=None):
        plugin_base = MagicMock()
        plugin_base.PATH = str(REPO_ROOT)
        plugin_base.get_settings.return_value = dict(settings or {})
        auth = self.mods.spotify_ctrl.AuthController(plugin_base)
        with patch.object(self.mods.spotify_ctrl.SpotifyController, "start_polling_updates"):
            ctrl = self.mods.spotify_ctrl.SpotifyController(plugin_base, auth, 2)
        plugin_base.get_controller = ctrl
        return plugin_base, auth, ctrl

    def test_repeat_action_handles_idle_and_uses_icon_paths(self):
        plugin_base, _, ctrl = self._make_controller()
        action = self.mods.repeat_mod.Repeat(plugin_base)

        with patch.object(ctrl, "get_repeat_state", return_value=None), \
             patch.object(ctrl, "set_repeat_state", return_value=True) as mock_set:
            action.on_key_down()
        mock_set.assert_called_once_with("off")
        self.assertEqual(action.media_calls[-1]["media_path"], action.no_repeat_icon)

        with patch.object(ctrl, "get_repeat_state", return_value="off"), \
             patch.object(ctrl, "set_repeat_state", return_value=True) as mock_set:
            action.on_key_down()
        mock_set.assert_called_once_with("track")
        self.assertEqual(action.media_calls[-1]["media_path"], action.repeat_one_icon)

    def test_volume_actions_ignore_none_volume(self):
        plugin_base, _, ctrl = self._make_controller()
        up = self.mods.volume_mod.VolumeUp(plugin_base)
        down = self.mods.volume_mod.VolumeDown(plugin_base)

        with patch.object(ctrl, "get_volume", return_value=None), \
             patch.object(ctrl, "set_volume") as mock_set:
            up.on_key_down()
            down.on_key_down()
        mock_set.assert_not_called()

        with patch.object(ctrl, "get_volume", return_value=95), \
             patch.object(ctrl, "set_volume") as mock_set:
            up.on_key_down()
        mock_set.assert_called_once_with(100)

    def test_device_action_close_toggle_and_destroy(self):
        plugin_base, _, ctrl = self._make_controller()
        action = self.mods.device_mod.SelectDevice(plugin_base)

        # Closing clears _active_dialog without calling nonexistent .destroy()
        dialog = MagicMock(spec=["present", "force_close"])
        action._active_dialog = dialog
        action._on_close_dialog(dialog)
        self.assertIsNone(action._active_dialog)

        # on_destroy uses force_close() via GLib.idle_add
        action._active_dialog = dialog
        with patch.object(self.mods.device_mod.GLib, "idle_add", side_effect=lambda fn, *a: fn(*a)):
            action.on_destroy()
        dialog.force_close.assert_called_once()
        self.assertIsNone(action._active_dialog)

        # Toggling inactive button does not trigger API; active button does.
        dev = self.mods.spotify_ctrl.Device("d1", False, False, False, "Desk", "Computer", 50, True)
        inactive_btn = MagicMock()
        inactive_btn.get_active.return_value = False
        active_btn = MagicMock()
        active_btn.get_active.return_value = True

        class SyncThread:
            def __init__(self, target, args=(), **kwargs):
                self._target, self._args = target, args

            def start(self):
                self._target(*self._args)

        with patch.object(ctrl, "set_playback_device") as mock_switch, \
             patch.object(self.mods.device_mod.threading, "Thread", SyncThread):
            action._on_select_device(inactive_btn, dev)
            mock_switch.assert_not_called()
            action._on_select_device(active_btn, dev)
            mock_switch.assert_called_once_with(dev)

    def test_polling_skips_when_unauthenticated_handles_null_item_ignores_timestamp_and_prunes_dead_cbs(self):
        _, auth, ctrl = self._make_controller(settings={})
        seen = []

        class Listener:
            def on_update(self, state):
                seen.append(state)

        listener = Listener()
        ctrl.register_update_callback(listener.on_update)

        # No token/refresh token -> does not hit Spotify API
        with patch.object(ctrl, "get_playback_state") as mock_get:
            ctrl._perform_update_and_notify()
        mock_get.assert_not_called()

        # Authenticated -> handles item=None, device=None, and ignores timestamp-only updates
        auth.access_token_obj = self.mods.spotify_ctrl.Token("tok", 3600)
        state1 = {"timestamp": 1, "item": None, "device": None, "is_playing": True, "shuffle_state": False, "repeat_state": "off"}
        state2 = {"timestamp": 2, "item": None, "device": None, "is_playing": True, "shuffle_state": False, "repeat_state": "off"}

        with patch.object(ctrl, "get_playback_state", side_effect=[state1, state2]), \
             patch.object(self.mods.spotify_ctrl.GLib, "idle_add", side_effect=lambda fn, *a: fn(*a)):
            ctrl._perform_update_and_notify()
            ctrl._perform_update_and_notify()
        self.assertEqual(len(seen), 1)

        # Dead listener is pruned automatically on GC
        del listener
        gc.collect()
        self.assertEqual(ctrl._live_callbacks(), [])

    def test_make_api_request_invalidates_token_on_401_and_controls_accept_200(self):
        _, auth, ctrl = self._make_controller(settings={"client_id": "c", "client_secret": "s"})
        auth.access_token_obj = self.mods.spotify_ctrl.Token("revoked", 3600)

        resp_401 = requests.Response()
        resp_401.status_code = 401
        resp_401.url = "https://api.spotify.com/v1/me/player"
        with patch.object(self.mods.spotify_ctrl.requests, "request", return_value=resp_401):
            with self.assertRaises(requests.HTTPError):
                ctrl._make_api_request("GET", resp_401.url)
        self.assertIsNone(auth.access_token_obj)

        # 200 OK counts as success for playback controls and device transfer
        auth.access_token_obj = self.mods.spotify_ctrl.Token("good", 3600)
        resp_200 = requests.Response()
        resp_200.status_code = 200
        dev = self.mods.spotify_ctrl.Device("d1", False, False, False, "Desk", "Computer", 50, True)
        with patch.object(self.mods.spotify_ctrl.requests, "request", return_value=resp_200):
            self.assertTrue(ctrl.play())
            self.assertTrue(ctrl.set_playback_device(dev))

    def test_play_resume_caches_album_art_and_uses_timeout(self):
        plugin_base, _, ctrl = self._make_controller()
        action = self.mods.play_mod.PlayResume(plugin_base)

        buf = io.BytesIO()
        Image.new("RGBA", (32, 32), (10, 20, 30, 255)).save(buf, format="PNG")
        img_resp = MagicMock()
        img_resp.content = buf.getvalue()
        img_resp.raise_for_status = MagicMock()

        class SyncThread:
            def __init__(self, target, args=(), **kwargs):
                self._target, self._args = target, args

            def start(self):
                self._target(*self._args)

        state_playing = {"is_playing": True, "item": {"album": {"images": [{"url": "https://img/cover.png"}]}}}
        state_paused = {"is_playing": False, "item": {"album": {"images": [{"url": "https://img/cover.png"}]}}}

        with patch.object(self.mods.play_mod.requests, "get", return_value=img_resp) as mock_get, \
             patch.object(self.mods.play_mod.threading, "Thread", SyncThread), \
             patch.object(self.mods.play_mod.GLib, "idle_add", side_effect=lambda fn, *a: fn(*a)):
            action.update_state(state_playing)
            action.update_state(state_paused)

        # Downloaded once with timeout, reused from cache on pause flip
        mock_get.assert_called_once_with("https://img/cover.png", timeout=10)

    def test_web_auth_strips_query_before_logging(self):
        self.assertEqual(
            self.mods.web_auth._strip_query("https://stream-controller/callback?code=SECRET_CODE"),
            "https://stream-controller/callback",
        )


if __name__ == "__main__":
    unittest.main()
