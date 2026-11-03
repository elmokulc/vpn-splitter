"""Exercise GTK/VTE on a disposable virtual display; profiles stay in a temp directory."""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main(xvfb):
    with tempfile.TemporaryDirectory(prefix="vpn-splitter-gui-") as temporary:
        os.environ["XDG_CONFIG_HOME"] = temporary
        display = subprocess.Popen(
            [xvfb, "-displayfd", "1", "-screen", "0", "1100x900x24", "-nolisten", "tcp"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            number = display.stdout.readline().strip()
            if not number:
                raise RuntimeError(display.stderr.read())
            os.environ["DISPLAY"] = f":{number}"
            import gi

            from vpn_splitter import __version__
            from vpn_splitter.gui import Desktop, GLib, Gtk
            from vpn_splitter.model import Application, Profile, ProfileStore

            gi.require_version("Gdk", "3.0")
            from gi.repository import Gdk

            ProfileStore().save(
                Profile(
                    "work",
                    "Work",
                    "https://vpn.example.test",
                    "alice",
                    applications=[
                        Application(
                            "Work Firefox",
                            ["/usr/bin/firefox", "--no-remote", "-P", "vpn-work"],
                        ),
                    ],
                )
            )
            app = Desktop(str(Path(temporary) / "no-service.sock"))
            app.set_application_id(f"org.vpnsplitter.SmokeTest.p{os.getpid()}")
            app.register(None)
            app.activate()
            failures = []
            loop = GLib.MainLoop()

            def test():
                try:
                    assert app.window.get_visible()
                    assert app.current().id == "work"
                    assert len(app.app_list.get_children()) == 1
                    header = app.window.get_titlebar()
                    about_button = next(
                        button
                        for button in header.get_children()
                        if isinstance(button, Gtk.Button) and button.get_label() == "About"
                    )
                    about_button.clicked()
                    dialog = next(
                        window
                        for window in Gtk.Window.list_toplevels()
                        if isinstance(window, Gtk.AboutDialog) and window.get_visible()
                    )
                    assert dialog.get_version() == __version__
                    assert dialog.get_transient_for() == app.window
                    dialog.response(Gtk.ResponseType.CLOSE)
                    app.start_connection()  # Real VTE subprocess; missing service is expected.
                except Exception as error:
                    failures.append(error)
                return False

            def finish():
                try:
                    assert not app.connecting, "VTE child-exited callback did not complete"
                    assert app.child_pid is None
                    assert app.snapshot.get("state") == "unavailable"
                    # Exercise the quit guard without connecting to the real service.
                    events = []
                    state = {"state": "blocked", "applications": [101, 102]}

                    def request(operation, **values):
                        if operation == "status":
                            return dict(state)
                        if operation == "disconnect":
                            events.append("disconnect")
                            return {}
                        raise AssertionError(operation)

                    def spin_until(predicate):
                        deadline = time.monotonic() + 3
                        context = GLib.MainContext.default()
                        while not predicate() and time.monotonic() < deadline:
                            while context.pending():
                                context.iteration(False)
                            time.sleep(0.01)
                        assert predicate(), "GUI operation did not complete"

                    def cancel_warning():
                        for window in Gtk.Window.list_toplevels():
                            if isinstance(window, Gtk.MessageDialog) and window.get_visible():
                                window.response(Gtk.ResponseType.CANCEL)
                                events.append("cancel")
                                return False
                        return True

                    real_quit = app.quit
                    app.quit = lambda: events.append("quit")
                    app.client.request = request
                    GLib.timeout_add(50, cancel_warning)
                    app.quit_desktop()
                    spin_until(lambda: "cancel" in events)
                    assert events == ["cancel"], events
                    state["applications"] = []
                    app.quit_desktop()
                    spin_until(lambda: "quit" in events)
                    assert events == ["cancel", "disconnect", "quit"], events
                    app.quit = real_quit
                    app.auth_expander.set_expanded(False)
                    width, height = app.window.get_size()
                    image = Gdk.pixbuf_get_from_window(app.window.get_window(), 0, 0, width, height)
                    (ROOT / "build").mkdir(exist_ok=True)
                    image.savev(str(ROOT / "build/gui-smoke.png"), "png", [], [])
                except Exception as error:
                    failures.append(error)
                app.window.destroy()
                app.quit()
                loop.quit()
                return False

            GLib.timeout_add(500, test)
            GLib.timeout_add_seconds(4, finish)
            loop.run()
            if failures:
                raise failures[0]
            print(
                "PASS: GTK window, About version, profile/application rendering, "
                "VTE spawn/exit, quit cancellation and disconnect-before-exit"
            )
        finally:
            display.terminate()
            display.communicate(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--xvfb", default="Xvfb")
    main(parser.parse_args().xvfb)
