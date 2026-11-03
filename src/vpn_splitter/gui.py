"""GTK desktop client. Privileged work is delegated to the installed service."""

from __future__ import annotations

import os
import shlex
import signal
import threading
import uuid
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gio, GLib, Gtk, Pango, Vte

from . import __version__
from .ipc import Client
from .linux import ALLOWED_ENVIRONMENT, ENTRY
from .model import Application, Profile, ProfileStore, SplitterError

CSS = b"""
window { background: #f4f6fa; }
.title { font-size: 24px; font-weight: bold; color: #17243d; }
.subtitle { color: #526179; }
.status { padding: 14px; background: #e5edf9; border-radius: 10px; }
.card { background: white; padding: 16px; border-radius: 10px; }
.command { color: #526179; font-size: 11px; }
"""


class Desktop(Gtk.Application):
    def __init__(self, socket_path):
        super().__init__(
            application_id="org.vpnsplitter.Desktop", flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        self.client = Client(socket_path)
        self.store = ProfileStore()
        self.window = None
        self.snapshot = {}
        self.polling = False
        self.child_pid = None
        self.connecting = False
        self.profiles = {}

    def do_activate(self):
        if self.window is not None:
            self.window.show_all()
            self.window.present()
            return
        self.hold()  # Closing the window must not tear down the authentication PTY/tunnel.
        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title("VPN Splitter")
        self.window.set_default_size(860, 720)
        self.window.connect("delete-event", self.hide_window)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(self.window.get_screen(), provider, 600)
        header = Gtk.HeaderBar(title="VPN Splitter", subtitle="Your VPN, one application at a time")
        header.set_show_close_button(True)
        about_button = Gtk.Button(label="About")
        about_button.connect("clicked", self.show_about)
        header.pack_start(about_button)
        quit_button = Gtk.Button(label="Quit")
        quit_button.connect("clicked", self.quit_desktop)
        header.pack_end(quit_button)
        self.window.set_titlebar(header)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin=24)
        self.window.add(root)
        title = Gtk.Label(label="Choose what goes through the VPN", xalign=0)
        title.get_style_context().add_class("title")
        root.pack_start(title, False, False, 0)
        description = Gtk.Label(label="Other applications keep their usual connection.", xalign=0)
        description.get_style_context().add_class("subtitle")
        root.pack_start(description, False, False, 0)
        self.status_label = Gtk.Label(label="Checking the service…", xalign=0)
        self.status_label.get_style_context().add_class("status")
        root.pack_start(self.status_label, False, False, 0)
        profiles_row = Gtk.Box(spacing=8)
        self.combo = Gtk.ComboBoxText()
        self.combo.set_hexpand(True)
        self.combo.connect("changed", lambda *_: self.render_applications())
        profiles_row.pack_start(self.combo, True, True, 0)
        for label, callback in (
            ("New profile", lambda *_: self.edit_profile()),
            ("Edit", lambda *_: self.edit_profile(self.current())),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", callback)
            profiles_row.pack_start(button, False, False, 0)
        root.pack_start(profiles_row, False, False, 0)
        actions = Gtk.Box(spacing=8)
        self.connect_button = Gtk.Button(label="Connect")
        self.connect_button.get_style_context().add_class("suggested-action")
        self.connect_button.connect("clicked", self.start_connection)
        self.disconnect_button = Gtk.Button(label="Disconnect and block")
        self.disconnect_button.connect("clicked", self.disconnect)
        reset = Gtk.Button(label="Reset empty session")
        reset.connect("clicked", lambda *_: self.background(lambda: self.client.request("reset")))
        for button in (self.connect_button, self.disconnect_button, reset):
            actions.pack_start(button, False, False, 0)
        root.pack_start(actions, False, False, 0)
        app_header = Gtk.Box(spacing=8)
        app_header.pack_start(
            Gtk.Label(label="Applications in this profile", xalign=0), True, True, 0
        )
        add = Gtk.Button(label="Add application")
        add.connect("clicked", self.add_application)
        app_header.pack_end(add, False, False, 0)
        root.pack_start(app_header, False, False, 0)
        self.app_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(130)
        scroll.add(self.app_list)
        root.pack_start(scroll, True, True, 0)
        note = Gtk.Label(
            label="VPN instances use separate desktop settings.\n"
            "Chrome and VS Code use a dedicated VPN profile. "
            "If the VPN drops, these instances stay blocked.",
            xalign=0,
            wrap=True,
        )
        note.get_style_context().add_class("subtitle")
        root.pack_start(note, False, False, 0)
        self.auth_expander = Gtk.Expander(label="Authentication and connection messages")
        self.terminal = Vte.Terminal()
        self.terminal.set_size(80, 10)
        self.terminal.set_scrollback_lines(500)
        self.terminal.connect("child-exited", self.child_exited)
        terminal_scroll = Gtk.ScrolledWindow()
        terminal_scroll.set_min_content_height(190)
        terminal_scroll.add(self.terminal)
        self.auth_expander.add(terminal_scroll)
        root.pack_start(self.auth_expander, False, True, 0)
        # StatusIcon is supported by desktops with a notification-area implementation.
        self.tray = Gtk.StatusIcon.new_from_icon_name("network-vpn")
        self.tray.set_tooltip_text("VPN Splitter — click to open")
        self.tray.connect("activate", lambda *_: self.activate())
        self.reload_profiles()
        GLib.timeout_add_seconds(2, self.poll)
        self.poll()
        self.window.show_all()

    def show_about(self, *_):
        dialog = Gtk.AboutDialog(
            transient_for=self.window,
            modal=True,
            destroy_with_parent=True,
            title="About VPN Splitter",
            program_name="VPN Splitter",
            version=__version__,
            comments="Your VPN, one application at a time.\n"
            "Version of the currently running interface.",
            logo_icon_name="vpn-splitter",
            license_type=Gtk.License.MIT_X11,
            copyright="Copyright (c) 2026 Christian Elmo",
        )
        dialog.connect("response", lambda widget, *_: widget.destroy())
        dialog.show_all()

    def current(self):
        return self.profiles.get(self.combo.get_active_id())

    def message(self, message):
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.CLOSE,
            text=str(message),
        )
        dialog.run()
        dialog.destroy()

    def background(self, work, success=None, quiet=False):
        def finish(value=None, error=None):
            if error is not None:
                if not quiet:
                    self.message(error)
            elif success:
                success(value)
            return False

        def worker():
            try:
                value = work()
            except Exception as error:
                GLib.idle_add(finish, None, str(error))
            else:
                GLib.idle_add(finish, value, None)

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.polling:
            return True
        self.polling = True

        def query():
            try:
                return self.client.request("status")
            except SplitterError:
                return {"state": "unavailable"}

        def update(snapshot):
            self.polling = False
            self.snapshot = snapshot
            states = {
                "unavailable": "Service unavailable — see the installation guide",
                "disconnected": "Disconnected — no session prepared",
                "blocked": "VPN unavailable — applications isolated and blocked",
                "connecting": "Connecting — enter your credentials below",
                "connected": "Tunnel attached — selected applications can use the VPN",
            }
            self.status_label.set_text(states.get(snapshot["state"], "Unknown state"))
            self.connect_button.set_sensitive(
                not self.connecting
                and snapshot["state"] in ("disconnected", "blocked")
                and self.current() is not None
            )
            self.disconnect_button.set_sensitive(
                snapshot["state"] not in ("unavailable", "disconnected")
            )
            self.render_applications()

        self.background(query, update, quiet=True)
        return True

    def reload_profiles(self, selected=None):
        try:
            profiles = self.store.list()
        except SplitterError as error:
            self.message(error)
            profiles = []
        self.profiles = {p.id: p for p in profiles}
        self.combo.remove_all()
        for profile in profiles:
            self.combo.append(profile.id, profile.name)
        if selected in self.profiles:
            self.combo.set_active_id(selected)
        elif profiles:
            self.combo.set_active(0)
        self.render_applications()

    def edit_profile(self, profile=None):
        dialog = Gtk.Dialog(title="AnyConnect profile", transient_for=self.window, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=14, row_spacing=10, margin=20)
        fields = {}
        for row, (key, label) in enumerate(
            (
                ("name", "Profile name"),
                ("server", "VPN HTTPS address"),
                ("username", "Username"),
                ("authgroup", "Group (optional)"),
                ("cafile", "CA certificate (optional path)"),
            )
        ):
            entry = Gtk.Entry()
            entry.set_width_chars(45)
            entry.set_text(
                getattr(profile, key) if profile else ("https://" if key == "server" else "")
            )
            fields[key] = entry
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(entry, 1, row, 1, 1)
        grid.attach(
            Gtk.Label(
                label="Password and OTP are requested when connecting and are never saved.",
                xalign=0,
            ),
            0,
            len(fields),
            2,
            1,
        )
        dialog.get_content_area().add(grid)
        dialog.show_all()
        while dialog.run() == Gtk.ResponseType.OK:
            try:
                candidate = Profile(
                    profile.id if profile else uuid.uuid4().hex[:12],
                    **{key: entry.get_text().strip() for key, entry in fields.items()},
                    applications=list(profile.applications) if profile else [],
                )
                self.store.save(candidate)
            except (SplitterError, OSError) as error:
                self.message(error)
                continue
            self.reload_profiles(candidate.id)
            break
        dialog.destroy()

    def render_applications(self):
        for row in self.app_list.get_children():
            self.app_list.remove(row)
        profile = self.current()
        if profile and profile.applications:
            for index, application in enumerate(profile.applications):
                row = Gtk.Box(spacing=12, margin=12)
                labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                labels.pack_start(Gtk.Label(label=application.name, xalign=0), False, False, 0)
                preview = Gtk.Label(label=shlex.join(application.argv), xalign=0)
                preview.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                preview.get_style_context().add_class("command")
                labels.pack_start(preview, False, False, 0)
                separate = Gtk.Label(label="Separate VPN configuration", xalign=0)
                separate.get_style_context().add_class("command")
                labels.pack_start(separate, False, False, 0)
                row.pack_start(labels, True, True, 0)
                launch = Gtk.Button(label="Launch in VPN")
                launch.set_sensitive(
                    self.snapshot.get("state") == "connected"
                    and self.snapshot.get("profile") == profile.id
                )
                launch.connect("clicked", lambda _, app=application: self.launch(app))
                row.pack_start(launch, False, False, 0)
                remove = Gtk.Button.new_from_icon_name("list-remove-symbolic", Gtk.IconSize.BUTTON)
                remove.set_tooltip_text("Remove from list (running processes stay isolated)")
                remove.connect("clicked", lambda _, i=index: self.remove_application(i))
                row.pack_start(remove, False, False, 0)
                self.app_list.add(row)
        else:
            self.app_list.add(
                Gtk.Label(label="Add a profile and the applications to protect.", margin=20)
            )
        self.app_list.show_all()

    def add_application(self, *_):
        profile = self.current()
        if profile is None:
            self.message("Create a VPN profile first.")
            return
        dialog = Gtk.Dialog(title="Add a native application", transient_for=self.window, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Add", Gtk.ResponseType.OK)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=20)
        name = Gtk.Entry(placeholder_text="Name: Work Firefox")
        command = Gtk.Entry(
            placeholder_text="/usr/bin/firefox --no-remote --profile /path/to/profile"
        )
        command.set_width_chars(65)
        for item in (name, command):
            box.pack_start(item, False, False, 0)
        box.pack_start(
            Gtk.Label(
                label="An absolute path is required. Snap/Flatpak applications are unsupported.",
                xalign=0,
            ),
            False,
            False,
            0,
        )
        dialog.get_content_area().add(box)
        dialog.show_all()
        while dialog.run() == Gtk.ResponseType.OK:
            try:
                application = Application(
                    name.get_text().strip(), shlex.split(command.get_text())
                ).validate()
                profile.applications.append(application)
                try:
                    self.store.save(profile)
                except Exception:
                    profile.applications.pop()
                    raise
            except (SplitterError, OSError, ValueError) as error:
                self.message(error)
                continue
            self.render_applications()
            break
        dialog.destroy()

    def remove_application(self, index):
        profile = self.current()
        profile.applications.pop(index)
        try:
            self.store.save(profile)
        except (SplitterError, OSError) as error:
            self.message(error)
        self.render_applications()

    def launch(self, application):
        environment = {k: v for k, v in os.environ.items() if k in ALLOWED_ENVIRONMENT}
        self.background(
            lambda: self.client.request(
                "launch", argv=application.argv, environment=environment, blocked=False
            )
        )

    def start_connection(self, *_):
        profile = self.current()
        if profile is None or self.connecting:
            return
        self.connecting = True
        self.connect_button.set_sensitive(False)
        self.auth_expander.set_expanded(True)
        self.terminal.reset(True, True)

        def spawned(terminal, pid, error, data):
            if error:
                self.connecting = False
                self.message(error.message)
            else:
                self.child_pid = pid
                terminal.grab_focus()

        self.terminal.spawn_async(
            Vte.PtyFlags.DEFAULT,
            str(Path.home()),
            [
                "/usr/bin/python3",
                "-I",
                str(ENTRY),
                "--socket",
                self.client.path,
                "connect",
                profile.id,
            ],
            None,
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            -1,
            None,
            spawned,
            None,
        )

    def child_exited(self, *_):
        self.child_pid = None
        self.connecting = False
        self.poll()

    def disconnect(self, *_):
        if self.child_pid:
            try:
                os.kill(self.child_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        self.background(lambda: self.client.request("disconnect"))

    def hide_window(self, *_):
        self.window.hide()
        return True

    def quit_desktop(self, *_):
        def inspect():
            try:
                return self.client.request("status")
            except SplitterError:
                return {"state": "unavailable", "applications": []}

        def confirm(snapshot):
            count = len(snapshot.get("applications", []))
            if count or snapshot["state"] == "unavailable":
                dialog = Gtk.MessageDialog(
                    transient_for=self.window,
                    modal=True,
                    message_type=Gtk.MessageType.WARNING,
                    buttons=Gtk.ButtonsType.NONE,
                    text="VPN applications may stay blocked after quitting",
                )
                dialog.format_secondary_text(
                    f"{count} VPN processes detected, including background processes. "
                    "Fully close the affected applications before quitting. "
                    "Quitting without closing them disconnects the VPN and leaves them blocked; "
                    "they are never automatically moved to a direct connection."
                    if snapshot["state"] != "unavailable"
                    else "The service is unavailable: processes cannot be checked. "
                    "Protected applications will not be moved to a direct connection."
                )
                dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
                dialog.add_button("Quit and leave applications blocked", Gtk.ResponseType.OK)
                dialog.set_default_response(Gtk.ResponseType.CANCEL)
                response = dialog.run()
                dialog.destroy()
                if response != Gtk.ResponseType.OK:
                    return
            self.finish_quit()

        self.background(inspect, confirm)

    def finish_quit(self):
        if self.child_pid:
            try:
                os.kill(self.child_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

        def stop():
            try:
                self.client.request("disconnect")
            except SplitterError:
                pass

        # Wait for the stop request before leaving GTK; do not abandon a daemon thread.
        self.background(stop, lambda _: self.quit())


def run(socket_path):
    if not Gtk.init_check()[0]:
        raise SplitterError("No graphical display available; use the CLI")
    return Desktop(socket_path).run([])
