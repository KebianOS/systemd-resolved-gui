import gettext
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk


DOMAIN = "systemd-resolved-gui"
LOCALE_DIR = os.environ.get(
    "SYSTEMD_RESOLVED_GUI_LOCALE_DIR",
    "/usr/share/locale",
)
_ = gettext.translation(DOMAIN, localedir=LOCALE_DIR, fallback=True).gettext

CONFIG_FILE = Path("/etc/systemd/resolved.conf")
ICON_FILE = (
    Path(__file__).resolve().parents[2]
    / "data/icons/hicolor/scalable/apps/systemd-resolved-gui.svg"
)
STATE_DIR = Path.home() / ".local/state/systemd-resolved-editor"
SNAPSHOT_FILE = STATE_DIR / "resolved.conf.original"
SNAPSHOT_INFO = STATE_DIR / "snapshot.json"
DEFAULT_CONFIG = "[Resolve]\n"


class ResolvedEditor(Gtk.Window):
    def __init__(self):
        super().__init__(title=_("systemd-resolved Editor"))
        icon_theme = Gtk.IconTheme.get_default()
        if ICON_FILE.is_file():
            icon_theme.append_search_path(str(ICON_FILE.parent))
        self.set_icon_name("systemd-resolved-gui")
        self.set_default_size(900, 650)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", self.on_close)
        self.connect("destroy", Gtk.main_quit)

        self.loading = False
        self.dirty = False
        self.snapshot_ready = False

        self.build_interface()
        self.editor.get_buffer().connect("changed", self.on_text_changed)
        self.install_shortcuts()
        self.load_theme_style()

        snapshot_error = None
        try:
            self.ensure_initial_snapshot()
        except (OSError, ValueError) as error:
            snapshot_error = error

        self.restore_button.set_sensitive(self.snapshot_ready)
        self.save_button.set_sensitive(self.snapshot_ready)
        self.load_config()
        if snapshot_error is not None:
            self.set_status(
                _(
                    "Could not create the restore point; "
                    "Save and Restore are disabled: %s"
                ) % snapshot_error
            )

    def build_interface(self):
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=14,
        )
        root.set_border_width(20)

        heading = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=5,
        )
        title = Gtk.Label(label="systemd-resolved")
        title.set_xalign(0)
        title.get_style_context().add_class("title")

        subtitle = Gtk.Label(label=str(CONFIG_FILE))
        subtitle.set_xalign(0)
        subtitle.get_style_context().add_class("subtitle")
        heading.pack_start(title, False, False, 0)
        heading.pack_start(subtitle, False, False, 0)

        self.editor = Gtk.TextView()
        self.editor.set_monospace(True)
        self.editor.set_wrap_mode(Gtk.WrapMode.NONE)
        self.editor.set_left_margin(14)
        self.editor.set_right_margin(14)
        self.editor.set_top_margin(12)
        self.editor.set_bottom_margin(12)

        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        scroller.add(self.editor)

        actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
        )
        self.reload_button = self.make_button(
            _("Reload"),
            "view-refresh-symbolic",
        )
        self.save_button = self.make_button(
            _("Save"),
            "document-save-symbolic",
        )
        self.restore_button = self.make_button(
            _("Restore original"),
            "edit-undo-symbolic",
        )
        self.reload_button.connect("clicked", self.on_reload)
        self.save_button.connect("clicked", self.on_save)
        self.restore_button.connect("clicked", self.on_restore)

        actions.pack_start(self.reload_button, False, False, 0)
        actions.pack_start(self.save_button, False, False, 0)
        actions.pack_end(self.restore_button, False, False, 0)

        self.status = Gtk.Label(label="")
        self.status.set_xalign(0)
        self.status.set_line_wrap(True)
        self.status.get_style_context().add_class("status")

        root.pack_start(heading, False, False, 0)
        root.pack_start(scroller, True, True, 0)
        root.pack_start(actions, False, False, 0)
        root.pack_start(self.status, False, False, 0)
        self.add(root)

    @staticmethod
    def make_button(label, icon_name):
        button = Gtk.Button.new_with_label(label)
        button.set_image(
            Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
        )
        button.set_always_show_image(True)
        return button

    def install_shortcuts(self):
        shortcuts = Gtk.AccelGroup()
        self.add_accel_group(shortcuts)
        self.save_button.add_accelerator(
            "clicked",
            shortcuts,
            Gdk.KEY_s,
            Gdk.ModifierType.CONTROL_MASK,
            Gtk.AccelFlags.VISIBLE,
        )

    def load_theme_style(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
            .title {
                font-size: 22px;
                font-weight: bold;
            }
            .subtitle {
                opacity: 0.75;
                font-family: monospace;
            }
            textview {
                font-family: monospace;
                font-size: 14px;
                background-color: @theme_base_color;
                color: @theme_text_color;
            }
            .status {
                padding-top: 6px;
                opacity: 0.85;
            }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def ensure_initial_snapshot(self):
        if SNAPSHOT_INFO.exists():
            info = json.loads(SNAPSHOT_INFO.read_text(encoding="utf-8"))
            if info.get("version") != 1 or not isinstance(
                info.get("existed"), bool
            ):
                raise ValueError(_("The restore point metadata is invalid."))
            if info["existed"] and not SNAPSHOT_FILE.is_file():
                raise ValueError(_("The original snapshot file is missing."))
            self.snapshot_ready = True
            return

        if SNAPSHOT_FILE.exists():
            raise ValueError(
                _("An incomplete restore point exists at %s; refusing to overwrite it.")
                % STATE_DIR
            )
        if CONFIG_FILE.is_symlink():
            raise ValueError(
                _("%s is a symbolic link; editing stopped for safety.")
                % CONFIG_FILE
            )

        STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = {"version": 1, "existed": CONFIG_FILE.exists()}

        if info["existed"]:
            metadata = CONFIG_FILE.stat()
            shutil.copy2(CONFIG_FILE, SNAPSHOT_FILE)
            info.update(
                mode=stat.S_IMODE(metadata.st_mode),
                uid=metadata.st_uid,
                gid=metadata.st_gid,
            )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=STATE_DIR,
            delete=False,
        ) as temporary:
            json.dump(info, temporary)
            temporary.write("\n")
            temporary_info = Path(temporary.name)
        os.replace(temporary_info, SNAPSHOT_INFO)
        self.snapshot_ready = True

    def set_editor_text(self, text):
        self.loading = True
        self.editor.get_buffer().set_text(text)
        self.loading = False
        self.dirty = False
        self.update_title()

    def load_config(self):
        try:
            if CONFIG_FILE.is_symlink():
                raise ValueError(_("The configuration file is a symbolic link."))
            if CONFIG_FILE.exists():
                text = CONFIG_FILE.read_text(encoding="utf-8")
                self.set_editor_text(text)
                self.set_status(_("Configuration loaded."))
            else:
                self.set_editor_text(DEFAULT_CONFIG)
                self.set_status(
                    _("The configuration file does not exist; showing a template.")
                )
        except (OSError, UnicodeError, ValueError) as error:
            self.set_status(_("Could not read the configuration: %s") % error)

    def get_editor_text(self):
        buffer = self.editor.get_buffer()
        start, end = buffer.get_bounds()
        return buffer.get_text(start, end, True)

    def set_status(self, message):
        self.status.set_text(message)

    def update_title(self):
        marker = " *" if self.dirty else ""
        self.set_title(_("systemd-resolved Editor") + marker)

    def on_text_changed(self, _buffer):
        if not self.loading:
            self.dirty = True
            self.update_title()
            self.set_status(_("There are unsaved changes."))

    def confirm(self, title, details, confirm_label):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=title,
        )
        dialog.format_secondary_text(details)
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(confirm_label, Gtk.ResponseType.ACCEPT)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.ACCEPT

    def confirm_discard(self):
        if not self.dirty:
            return True
        return self.confirm(
            _("There are unsaved changes"),
            _("Continuing will discard the edits in this window."),
            _("Discard changes"),
        )

    def run_as_admin(self, command):
        pkexec = shutil.which("pkexec")
        if not pkexec:
            raise RuntimeError(_("pkexec was not found on this system."))

        result = subprocess.run(
            [pkexec, *command],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            if not detail:
                detail = _("The operation was cancelled or denied.")
            raise RuntimeError(detail)

    def restart_resolved_service(self):
        systemctl = shutil.which("systemctl")
        if not systemctl:
            raise RuntimeError(_("The systemctl utility was not found."))
        self.run_as_admin(
            [systemctl, "restart", "systemd-resolved"]
        )

    def on_reload(self, _button):
        if self.confirm_discard():
            self.load_config()

    def on_save(self, _button):
        if not self.snapshot_ready:
            self.set_status(_("Cannot save: the original restore point is unavailable."))
            return
        if not self.confirm(
            _("Save the system configuration"),
            _(
                "This will replace %s. The initial state will be kept "
                "so you can restore it."
            ) % CONFIG_FILE,
            _("Save"),
        ):
            return

        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
            ) as temporary:
                temporary.write(self.get_editor_text())
                temporary_path = Path(temporary.name)

            install = shutil.which("install")
            if not install:
                raise RuntimeError(_("The install utility was not found."))

            self.run_as_admin(
                [
                    install,
                    "-o", "root",
                    "-g", "root",
                    "-m", "0644",
                    "--",
                    str(temporary_path),
                    str(CONFIG_FILE),
                ]
            )
            self.dirty = False
            self.update_title()
            try:
                self.restart_resolved_service()
            except RuntimeError as error:
                self.set_status(
                    _(
                        "Configuration saved, but systemd-resolved "
                        "could not be restarted: %s"
                    ) % error
                )
                return
            self.set_status(
                _("Configuration saved and systemd-resolved restarted.")
            )
        except (OSError, RuntimeError) as error:
            self.set_status(_("Could not save: %s") % error)
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass

    def on_restore(self, _button):
        if not self.snapshot_ready:
            self.set_status(_("There is no original restore point."))
            return
        if not self.confirm(
            _("Restore the original file"),
            _(
                "Unsaved edits will be discarded and the state captured "
                "when this editor was first opened will be restored."
            ),
            _("Restore"),
        ):
            return

        try:
            info = json.loads(SNAPSHOT_INFO.read_text(encoding="utf-8"))
            if info["existed"]:
                install = shutil.which("install")
                if not install:
                    raise RuntimeError(_("The install utility was not found."))
                self.run_as_admin(
                    [
                        install,
                        "-o", str(info["uid"]),
                        "-g", str(info["gid"]),
                        "-m", f"{info['mode']:04o}",
                        "--",
                        str(SNAPSHOT_FILE),
                        str(CONFIG_FILE),
                    ]
                )
            else:
                remove = shutil.which("rm")
                if not remove:
                    raise RuntimeError(_("The rm utility was not found."))
                self.run_as_admin([remove, "-f", "--", str(CONFIG_FILE)])

            self.load_config()
            try:
                self.restart_resolved_service()
            except RuntimeError as error:
                self.set_status(
                    _(
                        "Original state restored, but systemd-resolved "
                        "could not be restarted: %s"
                    ) % error
                )
                return
            self.set_status(
                _("Original state restored and systemd-resolved restarted.")
            )
        except (OSError, RuntimeError, KeyError, ValueError) as error:
            self.set_status(_("Could not restore: %s") % error)

    def on_close(self, _window, _event):
        return not self.confirm_discard()


def main():
    window = ResolvedEditor()
    window.show_all()
    Gtk.main()