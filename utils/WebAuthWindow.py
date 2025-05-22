from loguru import logger as log

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('WebKit', '6.0') # Or WebKit2GTK for older GTK3/WebKit versions
from gi.repository import Gtk, Adw, WebKit, Gio, GLib


def is_redirect_target(url):
    return url.startswith("https://stream-controller/callback") # Example


def _on_load_changed(webview, load_event):
    if load_event == WebKit.LoadEvent.FINISHED:
        current_uri = webview.get_uri()
        log.info(f"Load finished: {current_uri}")


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
        self.webview.connect("load-changed", _on_load_changed)
        # Connect to 'decide-policy' for more control (optional but good for redirects)
        self.webview.connect("decide-policy", self._on_decide_policy)

        self.webview.load_uri(self.initial_url)

    def _on_decide_policy(self, webview, decision, decision_type):
        if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            nav_action = decision.get_navigation_action()
            uri = nav_action.get_request().get_uri()
            log.info(f"Navigating to: {uri}")

            # THIS IS WHERE YOU'LL LIKELY DETECT THE REDIRECT
            # Add your specific logic to identify the target redirect URL
            if is_redirect_target(uri):
                self.redirected_url = uri
                log.info(f"Redirect target reached: {self.redirected_url}")
                self.close_and_extract()
                decision.ignore() # Stop the navigation in the webview
                return True
        # Allow other decisions (e.g., new window, download)
        return False # Let the default handler manage it

    def close_and_extract(self):
        log.info(f"Closing window. Extracted URL: {self.redirected_url}")
        code = self.redirected_url.split("https://stream-controller/callback?code=", 1)[1]
        log.info(f"Closing window. Extracted Code: {code}")
        self.close()
        if code and self.callback:
            GLib.idle_add(self.callback, code)
