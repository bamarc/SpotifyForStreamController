import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib import parse

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_plugin_modules():
    """Load plugin package with lightweight stubs for StreamController globals/PluginBase."""
    pkg_name = "spotify_plugin_testpkg"
    for name in list(sys.modules):
        if name == pkg_name or name.startswith(pkg_name + "."):
            del sys.modules[name]

    # Stub StreamController host modules
    src_mod = types.ModuleType("src")
    backend_mod = types.ModuleType("src.backend")
    pm_mod = types.ModuleType("src.backend.PluginManager")
    pb_mod = types.ModuleType("src.backend.PluginManager.PluginBase")
    ah_mod = types.ModuleType("src.backend.PluginManager.ActionHolder")

    class FakePluginBase:
        def __init__(self):
            self._settings = {}
            self.plugin_name = "Spotify For StreamController"

        def get_settings(self):
            # Return a fresh copy each time, matching StreamController disk-backed behavior.
            return dict(self._settings)

        def set_settings(self, settings):
            self._settings = dict(settings)

        def add_action_holder(self, holder):
            pass

        def register(self, **kwargs):
            pass

    pb_mod.PluginBase = FakePluginBase
    ah_mod.ActionHolder = MagicMock()

    globals_mod = types.ModuleType("globals")
    globals_mod.app = MagicMock()

    if "loguru" not in sys.modules:
        try:
            import loguru  # noqa: F401
        except ImportError:
            loguru_mod = types.ModuleType("loguru")
            loguru_mod.logger = MagicMock()
            sys.modules["loguru"] = loguru_mod

    # Stub actions to avoid loading StreamController ActionBase
    action_names = [
        ("PlayResumeAction", "PlayResume"),
        ("NextSongAction", "Next"),
        ("PreviousSongAction", "Previous"),
        ("ShuffleAction", "Shuffle"),
        ("RepeatAction", "Repeat"),
        ("DeviceActions", "SelectDevice"),
        ("VolumeActions", "VolumeDown"),
    ]

    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(REPO_ROOT)]
    utils_pkg = types.ModuleType(f"{pkg_name}.utils")
    utils_pkg.__path__ = [str(REPO_ROOT / "utils")]
    actions_pkg = types.ModuleType(f"{pkg_name}.actions")
    actions_pkg.__path__ = [str(REPO_ROOT / "actions")]
    media_pkg = types.ModuleType(f"{pkg_name}.actions.MediaActions")
    media_pkg.__path__ = [str(REPO_ROOT / "actions" / "MediaActions")]

    stubs = {
        "src": src_mod,
        "src.backend": backend_mod,
        "src.backend.PluginManager": pm_mod,
        "src.backend.PluginManager.PluginBase": pb_mod,
        "src.backend.PluginManager.ActionHolder": ah_mod,
        "globals": globals_mod,
        pkg_name: pkg,
        f"{pkg_name}.utils": utils_pkg,
        f"{pkg_name}.actions": actions_pkg,
        f"{pkg_name}.actions.MediaActions": media_pkg,
    }
    for mod_file, cls_name in action_names:
        m = types.ModuleType(f"{pkg_name}.actions.MediaActions.{mod_file}")
        setattr(m, cls_name, MagicMock())
        if mod_file == "VolumeActions":
            m.VolumeUp = MagicMock()
        stubs[m.__name__] = m

    sys.modules.update(stubs)

    def load(mod_name, rel_path):
        spec = importlib.util.spec_from_file_location(mod_name, REPO_ROOT / rel_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod

    web_auth = load(f"{pkg_name}.utils.WebAuthWindow", "utils/WebAuthWindow.py")
    spotify_ctrl = load(f"{pkg_name}.utils.SpotifyController", "utils/SpotifyController.py")
    main_mod = load(f"{pkg_name}.main", "main.py")
    return web_auth, spotify_ctrl, main_mod, globals_mod


class FakeEntryRow:
    def __init__(self, text=""):
        self._text = text

    def get_text(self):
        return self._text

    def set_text(self, text):
        self._text = text


class AuthFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web_auth, cls.spotify_ctrl, cls.main_mod, cls.gl = _load_plugin_modules()

    def _make_plugin(self):
        with patch.object(self.spotify_ctrl.SpotifyController, "start_polling_updates"):
            return self.main_mod.SpotifyForStreamController()

    def test_web_auth_extracts_code_with_extra_params_and_ignores_errors(self):
        received = []
        win = types.SimpleNamespace(
            callback=received.append,
            close=MagicMock(),
            redirected_url="https://stream-controller/callback?state=xyz&code=abc123&extra=1",
        )

        with patch.object(self.web_auth.GLib, "idle_add", side_effect=lambda fn, *a: fn(*a)):
            self.web_auth.WebAuthWindow.close_and_extract(win)
        self.assertEqual(received, ["abc123"])
        win.close.assert_called_once()

        # Error callback must close window without raising or invoking callback.
        received.clear()
        win.close.reset_mock()
        win.redirected_url = "https://stream-controller/callback?error=access_denied"
        with patch.object(self.web_auth.GLib, "idle_add", side_effect=lambda fn, *a: fn(*a)):
            self.web_auth.WebAuthWindow.close_and_extract(win)
        self.assertEqual(received, [])
        win.close.assert_called_once()

        # Duplicate decide-policy/load-changed signals only fire callback once.
        received.clear()
        win2 = types.SimpleNamespace(
            callback=received.append,
            close=MagicMock(),
            redirected_url=None,
        )
        win2.close_and_extract = lambda: self.web_auth.WebAuthWindow.close_and_extract(win2)
        decision = MagicMock()
        decision.get_navigation_action.return_value.get_request.return_value.get_uri.return_value = (
            "https://stream-controller/callback?code=once_only"
        )
        webview = MagicMock()
        webview.get_uri.return_value = "https://stream-controller/callback?code=once_only"

        with patch.object(self.web_auth.GLib, "idle_add", side_effect=lambda fn, *a: fn(*a)):
            self.assertTrue(
                self.web_auth.WebAuthWindow._on_decide_policy(
                    win2, webview, decision, self.web_auth.WebKit.PolicyDecisionType.NAVIGATION_ACTION
                )
            )
            self.web_auth.WebAuthWindow._on_load_changed(
                win2, webview, self.web_auth.WebKit.LoadEvent.REDIRECTED
            )
        decision.ignore.assert_called_once()
        self.assertEqual(received, ["once_only"])

    def test_on_login_persists_unsaved_rows_and_opens_auth_window_with_show_dialog(self):
        plugin = self._make_plugin()
        plugin.client_id_row = FakeEntryRow(" my_client_id ")
        plugin.client_secret_row = FakeEntryRow(" my_secret ")

        parent_win = MagicMock()
        self.gl.app.get_active_window.return_value = parent_win
        created_windows = []

        class FakeWindow:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.presented = False
                self.closed = False
                self.signals = {}
                created_windows.append(self)

            def connect(self, sig, cb):
                self.signals[sig] = cb

            def present(self):
                self.presented = True

            def close(self):
                self.closed = True

        with patch.object(self.spotify_ctrl, "WebAuthWindow", FakeWindow), \
             patch.object(self.main_mod.GLib, "idle_add", side_effect=lambda fn, *a: fn(*a)):
            plugin.on_login(None)

        self.assertEqual(plugin.get_settings()["client_id"], "my_client_id")
        self.assertEqual(plugin.get_settings()["client_secret"], "my_secret")
        self.assertEqual(len(created_windows), 1)
        win = created_windows[0]
        self.assertTrue(win.presented)
        self.assertIs(win.kwargs["transient_for"], parent_win)
        self.assertTrue(win.kwargs["modal"])
        qs = parse.parse_qs(parse.urlparse(win.kwargs["initial_url"]).query)
        self.assertEqual(qs["client_id"], ["my_client_id"])
        self.assertEqual(qs["show_dialog"], ["true"])

    def test_handle_auth_code_saves_code_exchanges_token_and_fills_both_ui_fields(self):
        plugin = self._make_plugin()
        plugin.set_settings({"client_id": "cid", "client_secret": "csec"})
        plugin.client_authorization_row = FakeEntryRow("")
        plugin.client_refresh_token_row = FakeEntryRow("")

        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "access_token": "acc_tok",
            "expires_in": 3600,
            "refresh_token": "ref_tok",
        }

        class SyncThread:
            def __init__(self, target, args=(), **kwargs):
                self._target = target
                self._args = args

            def start(self):
                self._target(*self._args)

        with patch.object(plugin.auth_controller, "_request_token_from_spotify", return_value=fake_resp), \
             patch.object(self.main_mod.threading, "Thread", SyncThread), \
             patch.object(self.main_mod.GLib, "idle_add", side_effect=lambda fn, *a: fn(*a)):
            res = plugin.handle_auth_code("auth_code_123")

        self.assertFalse(res)
        saved = plugin.get_settings()
        self.assertEqual(saved["client_authorization"], "auth_code_123")
        self.assertEqual(saved["client_refresh_token"], "ref_tok")
        self.assertEqual(plugin.client_authorization_row.get_text(), "auth_code_123")
        self.assertEqual(plugin.client_refresh_token_row.get_text(), "ref_tok")
        self.assertEqual(plugin.auth_controller.access_token_obj.value, "acc_tok")


if __name__ == "__main__":
    unittest.main()
