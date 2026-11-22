from urllib import parse
from loguru import logger as log

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('WebKit', '6.0')
from gi.repository import Adw, WebKit, GLib


def is_redirect_target(url):
    return url.startswith("https://stream-controller/callback")


def _strip_query(url: str) -> str:
    return url.split("?", 1)[0] if url else ""


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

        self.webview.connect("load-changed", self._on_load_changed)
        self.webview.connect("decide-policy", self._on_decide_policy)

        self.webview.load_uri(self.initial_url)

    def _on_load_changed(self, webview, load_event):
        current_uri = webview.get_uri()
        if current_uri and is_redirect_target(current_uri) and self.redirected_url is None:
            self.redirected_url = current_uri
            log.info(f"Redirect target reached on load-changed: {_strip_query(current_uri)}")
            self.close_and_extract()
        elif load_event == WebKit.LoadEvent.FINISHED:
            log.info(f"Load finished: {_strip_query(current_uri)}")

    def _on_decide_policy(self, webview, decision, decision_type):
        if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            nav_action = decision.get_navigation_action()
            uri = nav_action.get_request().get_uri()
            log.info(f"Navigating to: {_strip_query(uri)}")

            if is_redirect_target(uri):
                decision.ignore()  # Stop the navigation in the webview
                if self.redirected_url is None:
                    self.redirected_url = uri
                    log.info(f"Redirect target reached: {_strip_query(uri)}")
                    self.close_and_extract()
                return True
        return False

    def close_and_extract(self):
        params = parse.parse_qs(parse.urlparse(self.redirected_url).query)
        code = params.get("code", [None])[0]
        if code:
            log.info("Closing window. Authorization code extracted.")
        else:
            log.warning(f"Closing window. No authorization code in callback URL (error={params.get('error')}).")
        self.close()
        if code and self.callback:
            GLib.idle_add(self.callback, code)
