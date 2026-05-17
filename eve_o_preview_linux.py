#!/usr/bin/env python3
# EVE-O Preview for Linux (Live) – v5 click-or-drag with Enhanced UI
# - Left-click: focus client
# - Left-drag (move > threshold): move thumbnail
# - Right-click: move thumbnail
# - Ctrl+Left: minimize client
# - Thumbnails accept focus (fixes focus when main window isn't active)
# - Live previews via GdkX11 + gdk_pixbuf_get_from_window
# - Wayland: auto-detects and forces XWayland backend (EVE runs via XWayland anyway)

import os, sys, json, time, warnings, shutil, secrets
warnings.filterwarnings("ignore", category=DeprecationWarning)


def _ensure_proper_systemd_scope():
    """Re-exec into a properly-named systemd user scope.

    xdg-desktop-portal-kde derives the per-app identity used for
    GlobalShortcuts persistence from the *systemd cgroup scope* of the
    calling process — it looks for ``app-<APPID>-*.scope`` and uses
    ``APPID`` as the portal app_id. Launching from a terminal or a basic
    launcher (gtk-launch, gio launch) inherits the launcher's own scope
    (e.g. ``kitty-NNN.scope``), so xdp-kde sees ``app_id=""`` and our
    persisted ``[eve-o-preview]`` bindings can never be matched.

    Relocate by re-execing under ``systemd-run --user --scope`` with the
    expected unit name. The guard env var prevents an infinite re-exec
    loop if we're already inside the right scope (or systemd lies)."""
    if os.environ.get("EVE_O_PREVIEW_IN_SCOPE") == "1":
        return
    try:
        with open(f"/proc/{os.getpid()}/cgroup", "r") as f:
            cgroup = f.read()
    except OSError:
        return
    if "/app-eve-o-preview-" in cgroup:
        print(f"[eve-o-preview] scope OK: {cgroup.strip().splitlines()[-1]}",
              flush=True)
        return
    if shutil.which("systemd-run") is None:
        return
    print(f"[eve-o-preview] relocating from {cgroup.strip().splitlines()[-1]} "
          f"into a fresh app-eve-o-preview-*.scope", flush=True)
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS") is None and \
            os.environ.get("XDG_RUNTIME_DIR") is None:
        return  # no user systemd to talk to
    os.environ["EVE_O_PREVIEW_IN_SCOPE"] = "1"
    suffix = secrets.token_hex(4)
    cmd = [
        "systemd-run", "--user", "--scope", "--quiet", "--collect",
        f"--unit=app-eve-o-preview-{suffix}",
        sys.executable, os.path.abspath(__file__), *sys.argv[1:],
    ]
    try:
        with open("/tmp/eve-o-preview-settings.log", "a") as _lg:
            _lg.write(f"[{__import__('time').time():.3f}] relocate pid={os.getpid()} "
                      f"-> {' '.join(cmd)}\n")
    except OSError:
        pass
    try:
        os.execvp(cmd[0], cmd)
    except OSError as e:
        # Fall through and run in the wrong scope — better than crashing.
        print(f"[eve-o-preview] scope relocation skipped: {e}", file=sys.stderr)


_ensure_proper_systemd_scope()

# Startup trace — written every launch (after any scope relocation).
# Survives stdout detachment, so launcher-spawned crashes leave evidence.
try:
    with open("/tmp/eve-o-preview-settings.log", "a") as _lg:
        _lg.write(f"\n[{time.time():.3f}] === launch pid={os.getpid()} ===\n")
        _lg.write(f"  argv={sys.argv}\n")
        try:
            with open(f"/proc/{os.getpid()}/cgroup") as _cg:
                _lg.write(f"  cgroup={_cg.read().strip().splitlines()[-1]}\n")
        except OSError:
            pass
        for _k in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE",
                   "GDK_BACKEND", "DBUS_SESSION_BUS_ADDRESS",
                   "XDG_CURRENT_DESKTOP", "EVE_O_PREVIEW_IN_SCOPE"):
            _lg.write(f"  {_k}={os.environ.get(_k, '<unset>')}\n")
except OSError:
    pass

# Wayland detection: if running under Wayland, force GDK to use the X11/XWayland
# backend. EVE Online on Linux always runs through Wine/Proton -> XWayland, so
# window capture via GdkX11 works correctly. Native Wayland capture requires
# PipeWire (Phase 2).
_WAYLAND_SESSION = bool(os.environ.get("WAYLAND_DISPLAY") or
                        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland")
if _WAYLAND_SESSION:
    os.environ["GDK_BACKEND"] = "x11"
    print("[eve-o-preview] Wayland detected — running via XWayland backend.")
    print("[eve-o-preview] EVE clients (Wine/Proton) are XWayland windows, capture works normally.")
else:
    os.environ.setdefault("GDK_BACKEND", "x11")
    print("[eve-o-preview] X11 session detected.")

# Detect gtk-layer-shell for native Wayland OVERLAY support.
# The main process stays on x11 backend (Wnck requires it); layer-shell
# thumbnails run as subprocesses with GDK_BACKEND=wayland.
_LAYER_SHELL_AVAILABLE = False
if _WAYLAND_SESSION:
    import subprocess as _sp, sys as _sys
    try:
        _r = _sp.run(
            [_sys.executable, "-c",
             "import os; os.environ['GDK_BACKEND']='wayland';"
             "import gi; gi.require_version('GtkLayerShell','0.1');"
             "from gi.repository import GtkLayerShell; print('ok')"],
            capture_output=True, timeout=5)
        _LAYER_SHELL_AVAILABLE = b'ok' in _r.stdout
    except Exception:
        pass
    del _sp, _sys
    if _LAYER_SHELL_AVAILABLE:
        print("[eve-o-preview] gtk-layer-shell detected — thumbnails will use Wayland OVERLAY (above fullscreen).")
    else:
        print("[eve-o-preview] gtk-layer-shell not found — thumbnails may go under Fixed Window EVE.")
        print("[eve-o-preview]   Fedora:  sudo dnf install gtk-layer-shell")
        print("[eve-o-preview]   Ubuntu:  sudo apt install gir1.2-gtk-layer-shell-0")

import gi
try:
    gi.require_version('Gtk', '3.0')
    gi.require_version('Wnck', '3.0')
    gi.require_version('GdkX11', '3.0')
except ValueError as _e:
    missing = str(_e)
    print(f"\n[eve-o-preview] ERROR: Missing GObject Introspection typelib — {missing}")
    print("  Install the required system packages and try again:")
    print("  Fedora:  sudo dnf install libwnck3 gtk3 python3-gobject")
    print("  Ubuntu:  sudo apt install gir1.2-wnck-3.0 gir1.2-gtk-3.0 python3-gi")
    raise SystemExit(1)
from gi.repository import Gtk, Gdk, GdkPixbuf, Wnck, GLib, GdkX11
import ctypes, ctypes.util

# ---------------------------------------------------------------------------
# gtk-layer-shell subprocess helper script
# Each thumbnail spawns one instance of this script with GDK_BACKEND=wayland.
# It creates a GtkLayerShell OVERLAY window — guaranteed above every fullscreen
# surface by the Wayland compositor — and communicates via stdin/stdout pipes.
# ---------------------------------------------------------------------------
_LAYER_SHELL_HELPER = r"""
import sys, os, base64, threading, time as _time, ctypes as _ct
os.environ.setdefault("GDK_BACKEND", "wayland")

# ---------------------------------------------------------------------------
# XQueryPointer — true screen-absolute pointer position via X11/XWayland.
# GDK3 Wayland derives "root" coordinates as window_origin + local_x, but
# for layer-shell windows it uses origin=(0,0), making "root" == window-local.
# XQueryPointer bypasses GDK and queries XWayland directly, giving the real
# screen-absolute position regardless of where the layer-shell surface sits.
# ---------------------------------------------------------------------------
class _X11Ptr:
    def __init__(self):
        self._dpy = None
        self._root = None
        try:
            _xlib = _ct.cdll.LoadLibrary("libX11.so.6")
            _xlib.XOpenDisplay.restype  = _ct.c_void_p
            _xlib.XOpenDisplay.argtypes = [_ct.c_char_p]
            _xlib.XDefaultRootWindow.restype  = _ct.c_ulong
            _xlib.XDefaultRootWindow.argtypes = [_ct.c_void_p]
            _xlib.XQueryPointer.restype  = _ct.c_int
            dpy = _xlib.XOpenDisplay(None)
            if dpy:
                self._xlib = _xlib
                self._dpy  = _ct.c_void_p(dpy)
                self._root = _xlib.XDefaultRootWindow(self._dpy)
        except Exception:
            pass

    def get_pos(self):
        if not self._dpy:
            return None, None
        try:
            rx, ry = _ct.c_int(), _ct.c_int()
            wx, wy = _ct.c_int(), _ct.c_int()
            mask   = _ct.c_uint()
            r_ret  = _ct.c_ulong()
            child  = _ct.c_ulong()
            self._xlib.XQueryPointer(
                self._dpy, self._root,
                _ct.byref(r_ret), _ct.byref(child),
                _ct.byref(rx), _ct.byref(ry),
                _ct.byref(wx), _ct.byref(wy),
                _ct.byref(mask))
            return rx.value, ry.value
        except Exception:
            return None, None

_x11ptr = _X11Ptr()
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GdkPixbuf, GtkLayerShell, GLib

class _Thumb(Gtk.Window):
    def __init__(self):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        self.set_decorated(False)

        # Overlay: image + character name label
        self._ov = Gtk.Overlay()
        self._img = Gtk.Image()
        self._ov.add(self._img)

        self._lbl = Gtk.Label()
        self._lbl.set_halign(Gtk.Align.CENTER)
        self._lbl.set_valign(Gtk.Align.START)
        self._lbl.set_margin_top(4)
        _lbl_css = Gtk.CssProvider()
        _lbl_css.load_from_data(
            b"label { background: rgba(0,0,0,0.7); color: white;"
            b"  padding: 4px 8px; border-radius: 3px; font-size: 11px; }")
        self._lbl.get_style_context().add_provider(
            _lbl_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._lbl.set_no_show_all(True)
        self._ov.add_overlay(self._lbl)

        self.add(self._ov)

        # Border drawn via Cairo.
        # IMPORTANT: connect_after so our draw runs AFTER children paint —
        # connect() fires before the default handler (SIGNAL_RUN_LAST) which
        # draws children, so a plain connect() puts the border UNDER the image.
        self._border_color = None
        self.connect_after("draw", self._draw_border)

        # Drag / click state
        self._mx = self._my = 0
        self._last_drag_x = self._last_drag_y = 0.0
        self._drag_dist = 0.0
        self._drag = False
        self._ctrl = False
        self._btn_down = False
        self._last_click_emit = 0.0   # debounce: ignore rapid repeat clicks

        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.ENTER_NOTIFY_MASK |
            Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        self.connect("button-press-event", self._on_press)
        self.connect("button-release-event", self._on_release)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("enter-notify-event", self._on_enter)
        self.connect("leave-notify-event", self._on_leave)

    def set_pos(self, x, y):
        self._mx, self._my = x, y
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, x)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, y)

    def set_frame(self, w, h, rs, data):
        # new_from_bytes() wraps data in a GLib.Bytes that the pixbuf keeps
        # alive — unlike new_from_data(destroy_fn=None) which holds a raw
        # pointer that Python's GC can free while the pixbuf still uses it.
        try:
            pb = GdkPixbuf.Pixbuf.new_from_bytes(
                GLib.Bytes.new(data),
                GdkPixbuf.Colorspace.RGB, True, 8, w, h, rs)
            self._img.set_from_pixbuf(pb)
        except Exception as e:
            sys.stderr.write(f"frame: {e}\n")

    def set_active(self, is_active, color):
        self._border_color = color if is_active else None
        self.queue_draw()

    def set_title(self, title):
        if title:
            self._lbl.set_markup(f"<b>{title}</b>")
            self._lbl.show()
        else:
            self._lbl.hide()

    def _draw_border(self, w, cr):
        if not self._border_color:
            return False
        try:
            h = self._border_color.lstrip('#')
            r, g, b = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
        except Exception:
            return False
        alloc = w.get_allocation()
        cr.set_source_rgba(r, g, b, 1.0)
        cr.set_line_width(4)
        cr.rectangle(2, 2, alloc.width - 4, alloc.height - 4)
        cr.stroke()
        return False  # allow default rendering

    def _emit(self, msg):
        try:
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()
        except Exception:
            pass

    def _on_press(self, w, ev):
        if ev.button in (1, 3):
            self._ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
            # Seed the relative-motion reference with the surface-local press
            # position.  All drag movement is tracked as deltas between
            # consecutive motion events — no absolute coordinates needed.
            self._last_drag_x = ev.x
            self._last_drag_y = ev.y
            self._drag_dist = 0.0
            self._drag = False
            self._btn_down = True
            return True
        return False

    def _on_motion(self, w, ev):
        if not self._btn_down:
            return False
        dx = ev.x - self._last_drag_x
        dy = ev.y - self._last_drag_y
        self._last_drag_x = ev.x
        self._last_drag_y = ev.y
        self._drag_dist += abs(dx) + abs(dy)
        if self._drag_dist > 4:
            self._drag = True
        if self._drag:
            nx = max(0, self._mx + int(dx))
            ny = max(0, self._my + int(dy))
            if nx != self._mx or ny != self._my:
                self.set_pos(nx, ny)
                self._emit(f"POS {nx} {ny}")
        return True

    def _on_release(self, w, ev):
        if ev.button in (1, 3):
            was_drag = self._drag
            if not was_drag and ev.button == 1:
                # Debounce: GTK generates PRESS+RELEASE twice for a double-click
                # event, which would send CLICK twice in rapid succession and
                # trigger multiple wmctrl/focus calls.  Suppress any CLICK that
                # arrives within 400 ms of the previous one.
                now = _time.monotonic()
                if now - self._last_click_emit >= 0.4:
                    self._last_click_emit = now
                    self._emit("CTRL_CLICK" if self._ctrl else "CLICK")
            self._drag = False
            self._btn_down = False
            # If drag just ended and cursor is still on window, fire ENTER
            # so the main process zoom debounce restarts cleanly.
            if was_drag:
                self._emit("ENTER")
            return True
        return False

    def _on_enter(self, w, ev):
        if self._btn_down:
            # The compositor sends LEAVE+ENTER when our set_pos() moves the
            # window under the cursor.  ENTER fires AFTER the compositor has
            # applied the new margin, so ev.x is already in the new surface-
            # local frame.  Re-anchor the drag reference here so the next
            # motion event's delta is relative to the correct origin.
            self._last_drag_x = ev.x
            self._last_drag_y = ev.y
            # Do NOT emit ENTER during a drag — prevents zoom thrash as the
            # window moves through LEAVE+ENTER cycles on every set_pos().
            return False
        self._emit("ENTER")
        return False

    def _on_leave(self, w, ev):
        if self._btn_down:
            return False   # suppress zoom-out during drag
        self._emit("LEAVE")
        return False

win = _Thumb()
win.show_all()

def _reader():
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        if not line:
            continue
        parts = line.split(" ", 4)
        cmd = parts[0]
        try:
            if cmd == "FRAME" and len(parts) == 5:
                w, h, rs = int(parts[1]), int(parts[2]), int(parts[3])
                data = base64.b64decode(parts[4])
                GLib.idle_add(win.set_frame, w, h, rs, data)
            elif cmd == "POS" and len(parts) == 3:
                GLib.idle_add(win.set_pos, int(parts[1]), int(parts[2]))
            elif cmd == "SIZE" and len(parts) == 3:
                GLib.idle_add(win.resize, int(parts[1]), int(parts[2]))
            elif cmd == "ACTIVE" and len(parts) == 3:
                GLib.idle_add(win.set_active, parts[1] == "1", parts[2])
            elif cmd == "TITLE":
                GLib.idle_add(win.set_title, " ".join(parts[1:]))
            elif cmd == "SHOW":
                GLib.idle_add(win.show)
            elif cmd == "HIDE":
                GLib.idle_add(win.hide)
            elif cmd == "QUIT":
                GLib.idle_add(Gtk.main_quit)
                return
        except Exception as e:
            sys.stderr.write(f"helper [{cmd}]: {e}\n")
    GLib.idle_add(Gtk.main_quit)

threading.Thread(target=_reader, daemon=True).start()
Gtk.main()
"""

import base64 as _b64mod, subprocess as _subproc, threading as _threading
import queue as _queue_mod

class _LayerShellDisplay:
    """Manages a layer-shell subprocess OVERLAY window for one thumbnail."""

    def __init__(self, x, y, w, h, click_cb, ctrl_click_cb, pos_cb,
                 enter_cb=None, leave_cb=None):
        import sys as _sys
        self._x, self._y = x, y
        self._click_cb = click_cb
        self._ctrl_click_cb = ctrl_click_cb
        self._pos_cb = pos_cb
        self._enter_cb = enter_cb
        self._leave_cb = leave_cb
        # Two queues funnelled through one background writer thread so the
        # GTK main thread NEVER writes to stdin and can never block.
        #
        # _ctrl_queue: unlimited size — SIZE, POS, ACTIVE, TITLE, SHOW, HIDE,
        #   QUIT messages; always delivered in order, never dropped.
        # _frame_queue: size=1 — large FRAME payloads; stale frames are
        #   silently replaced so the subprocess always gets the newest image.
        self._ctrl_queue  = _queue_mod.Queue()          # unbounded
        self._frame_queue = _queue_mod.Queue(maxsize=1) # drop-old
        env = os.environ.copy()
        env["GDK_BACKEND"] = "wayland"
        self._proc = _subproc.Popen(
            [_sys.executable, "-c", _LAYER_SHELL_HELPER],
            stdin=_subproc.PIPE,
            stdout=_subproc.PIPE,
            stderr=None,   # inherit terminal so subprocess errors are visible
            env=env,
        )
        _threading.Thread(target=self._reader, daemon=True).start()
        _threading.Thread(target=self._writer, daemon=True).start()
        self._ctrl_send(f"SIZE {w} {h}")
        self._ctrl_send(f"POS {x} {y}")

    # ------------------------------------------------------------------
    # Internal helpers — only called from the background _writer thread
    # or at startup before concurrent access begins.

    def _ctrl_send(self, msg):
        """Enqueue a small control message (non-blocking, never dropped)."""
        self._ctrl_queue.put((msg + "\n").encode())

    def _writer(self):
        """Single background thread that owns all stdin writes.

        Drains all pending control messages before sending each frame, so
        that ACTIVE/POS/SIZE updates are never delayed behind a large FRAME
        payload.  When no frame is available the loop blocks briefly on the
        control queue so we don't spin-loop consuming CPU.
        """
        stdin = self._proc.stdin
        while True:
            try:
                # 1. Flush all queued control messages first (non-blocking).
                while True:
                    try:
                        data = self._ctrl_queue.get_nowait()
                        if data is None:
                            return   # QUIT sentinel
                        stdin.write(data)
                    except _queue_mod.Empty:
                        break

                # 2. Try to send one frame.
                try:
                    data = self._frame_queue.get_nowait()
                    stdin.write(data)
                    stdin.flush()
                    continue
                except _queue_mod.Empty:
                    pass

                # 3. Nothing to write — wait for next control message,
                #    flushing any partial writes first.
                try:
                    stdin.flush()
                except Exception:
                    pass
                try:
                    data = self._ctrl_queue.get(timeout=0.05)
                    if data is None:
                        return
                    stdin.write(data)
                except _queue_mod.Empty:
                    pass

            except Exception:
                break

    def _reader(self):
        try:
            for line_b in iter(self._proc.stdout.readline, b""):
                line = line_b.decode("utf-8", errors="replace").strip()
                if IPC_DEBUG and line and not line.startswith("FRAME"):
                    print(f"[ipc] {line}", flush=True)
                # CRITICAL: Use GLib.idle_add with GLib.PRIORITY_HIGH (-100)
                # instead of default idle priority (200).  With two clients the
                # capture timers (priority 0) consume most main-loop time, and
                # default-priority idle callbacks are starved indefinitely — this
                # is the root cause of click/zoom/hover death on second client.
                _P = GLib.PRIORITY_HIGH
                if line == "CLICK" and self._click_cb:
                    GLib.idle_add(self._click_cb, priority=_P)
                elif line == "CTRL_CLICK" and self._ctrl_click_cb:
                    GLib.idle_add(self._ctrl_click_cb, priority=_P)
                elif line.startswith("POS ") and self._pos_cb:
                    p = line.split()
                    if len(p) == 3:
                        GLib.idle_add(self._pos_cb, int(p[1]), int(p[2]), priority=_P)
                elif line == "ENTER" and self._enter_cb:
                    GLib.idle_add(self._enter_cb, priority=_P)
                elif line == "LEAVE" and self._leave_cb:
                    GLib.idle_add(self._leave_cb, priority=_P)
        except Exception:
            pass

    def send_frame(self, pixbuf):
        if not pixbuf:
            return
        if not pixbuf.get_has_alpha():
            pixbuf = pixbuf.add_alpha(False, 0, 0, 0)
        w, h, rs = pixbuf.get_width(), pixbuf.get_height(), pixbuf.get_rowstride()
        b64 = _b64mod.b64encode(bytes(pixbuf.get_pixels())).decode("ascii")
        data = f"FRAME {w} {h} {rs} {b64}\n".encode()
        # Replace stale frame with the newest one; never block.
        try:
            self._frame_queue.put_nowait(data)
        except _queue_mod.Full:
            try:
                self._frame_queue.get_nowait()
            except _queue_mod.Empty:
                pass
            try:
                self._frame_queue.put_nowait(data)
            except _queue_mod.Full:
                pass

    def set_pos(self, x, y):
        self._x, self._y = x, y
        self._ctrl_send(f"POS {x} {y}")

    def set_size(self, w, h):
        self._ctrl_send(f"SIZE {w} {h}")

    def send_active(self, is_active, color):
        self._ctrl_send(f"ACTIVE {'1' if is_active else '0'} {color}")

    def send_title(self, title):
        self._ctrl_send(f"TITLE {title}")

    def show(self):
        self._ctrl_send("SHOW")

    def hide(self):
        self._ctrl_send("HIDE")

    def destroy(self):
        self._ctrl_send("QUIT")
        try:
            self._proc.stdin.close()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Xlib helpers — own display connection (avoids GDK pointer casting issues)
# ---------------------------------------------------------------------------
_xlib      = None
_xlib_dpy  = None   # our own Display* for XQueryTree / child discovery

def _get_xlib():
    global _xlib
    if _xlib is None:
        path = ctypes.util.find_library("X11")
        if path:
            _xlib = ctypes.CDLL(path)
            _xlib.XOpenDisplay.restype  = ctypes.c_void_p
            _xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            _xlib.XQueryTree.restype    = ctypes.c_int
            _xlib.XFree.restype         = ctypes.c_int
    return _xlib

def _xlib_display():
    global _xlib_dpy
    if _xlib_dpy is None:
        xlib = _get_xlib()
        if xlib:
            _xlib_dpy = xlib.XOpenDisplay(None)
    return _xlib_dpy

def _net_activate_window(xid, timestamp=0):
    """Send _NET_ACTIVE_WINDOW ClientMessage to bring an XWayland window forward.

    This is what wmctrl/xdotool do internally. We use it instead of Wnck so we
    have full control over the message fields (source=1 = direct user action,
    which KWin respects even with focus-stealing-prevention enabled).

    If the X11 window is currently unmapped (e.g. EVE's loading screen
    temporarily withdraws the XWayland surface), XMapWindow re-maps it first so
    that XSetInputFocus and the WM activation message can both succeed.
    """
    xlib = _get_xlib()
    dpy  = _xlib_display()
    if not xlib or not dpy:
        return False
    try:
        xlib.XDefaultRootWindow.restype  = ctypes.c_ulong
        xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        xlib.XInternAtom.restype  = ctypes.c_ulong
        xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        xlib.XSendEvent.restype   = ctypes.c_int
        xlib.XRaiseWindow.restype = ctypes.c_int
        xlib.XFlush.restype       = ctypes.c_int

        # Map the window in case it is currently unmapped (loading screen).
        try:
            xlib.XMapWindow.restype  = ctypes.c_int
            xlib.XMapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            xlib.XMapWindow(ctypes.c_void_p(dpy), ctypes.c_ulong(xid))
        except Exception:
            pass

        root = xlib.XDefaultRootWindow(ctypes.c_void_p(dpy))
        atom = xlib.XInternAtom(ctypes.c_void_p(dpy), b"_NET_ACTIVE_WINDOW", False)

        # XClientMessageEvent — pad the struct to 96 bytes (XEvent union size).
        class _MsgData(ctypes.Union):
            _fields_ = [("l", ctypes.c_long * 5), ("b", ctypes.c_char * 20)]

        class _XClientMsg(ctypes.Structure):
            _fields_ = [
                ("type",         ctypes.c_int),
                ("serial",       ctypes.c_ulong),
                ("send_event",   ctypes.c_int),
                ("display",      ctypes.c_void_p),
                ("window",       ctypes.c_ulong),
                ("message_type", ctypes.c_ulong),
                ("format",       ctypes.c_int),
                ("data",         _MsgData),
                ("_pad",         ctypes.c_char * 64),  # XEvent is 96 bytes min
            ]

        ev = _XClientMsg()
        ev.type         = 33   # ClientMessage
        ev.send_event   = 1
        ev.display      = dpy
        ev.window       = xid
        ev.message_type = atom
        ev.format       = 32
        ev.data.l[0]    = 1          # source=1: direct user action (KWin honours this)
        ev.data.l[1]    = timestamp  # real X11 server timestamp avoids FSP rejection
        ev.data.l[2]    = 0          # currently active window (unknown)

        mask = 0x80000 | 0x100000  # SubstructureNotify | SubstructureRedirect
        xlib.XSendEvent(ctypes.c_void_p(dpy), root, 0, mask, ctypes.byref(ev))
        xlib.XRaiseWindow(ctypes.c_void_p(dpy), ctypes.c_ulong(xid))
        # XSetInputFocus: directly assign X11 keyboard focus — bypasses WM
        # focus-stealing-prevention (works for XWayland windows because the
        # XWayland compositor bridges X11 focus to Wayland seat focus).
        try:
            xlib.XSetInputFocus.restype  = ctypes.c_int
            xlib.XSetInputFocus.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            xlib.XSetInputFocus(
                ctypes.c_void_p(dpy), ctypes.c_ulong(xid),
                1,          # RevertToPointerRoot
                timestamp,  # use same real timestamp
            )
        except Exception:
            pass
        # WM_TAKE_FOCUS: some Wine windows use ICCCM protocol and won't respond
        # to XSetInputFocus alone.  Send them a ClientMessage as well so they
        # know they're being asked to accept focus.
        try:
            wm_protocols  = xlib.XInternAtom(ctypes.c_void_p(dpy), b"WM_PROTOCOLS",  False)
            wm_take_focus = xlib.XInternAtom(ctypes.c_void_p(dpy), b"WM_TAKE_FOCUS", False)

            class _MsgData2(ctypes.Union):
                _fields_ = [("l", ctypes.c_long * 5), ("b", ctypes.c_char * 20)]

            class _XTakeFocus(ctypes.Structure):
                _fields_ = [
                    ("type",         ctypes.c_int),
                    ("serial",       ctypes.c_ulong),
                    ("send_event",   ctypes.c_int),
                    ("display",      ctypes.c_void_p),
                    ("window",       ctypes.c_ulong),
                    ("message_type", ctypes.c_ulong),
                    ("format",       ctypes.c_int),
                    ("data",         _MsgData2),
                    ("_pad",         ctypes.c_char * 64),
                ]

            tf = _XTakeFocus()
            tf.type         = 33   # ClientMessage
            tf.send_event   = 1
            tf.display      = dpy
            tf.window       = xid
            tf.message_type = wm_protocols
            tf.format       = 32
            tf.data.l[0]    = wm_take_focus
            tf.data.l[1]    = timestamp if timestamp else 1
            xlib.XSendEvent(ctypes.c_void_p(dpy), ctypes.c_ulong(xid), False, 0, ctypes.byref(tf))
        except Exception:
            pass

        xlib.XFlush(ctypes.c_void_p(dpy))
        return True
    except Exception as e:
        print(f"[activate] xlib error: {e}")
        return False

def _get_child_xids(parent_xid):
    """Return list of direct child XIDs (empty list if none / error)."""
    xlib = _get_xlib()
    dpy  = _xlib_display()
    if not xlib or not dpy:
        return []
    try:
        root_out   = ctypes.c_ulong(0)
        parent_out = ctypes.c_ulong(0)
        children_p = ctypes.c_void_p(0)
        n_children = ctypes.c_uint(0)
        xlib.XQueryTree(
            ctypes.c_void_p(dpy),
            ctypes.c_ulong(parent_xid),
            ctypes.byref(root_out),
            ctypes.byref(parent_out),
            ctypes.byref(children_p),
            ctypes.byref(n_children),
        )
        count = n_children.value
        if count == 0 or not children_p.value:
            return []
        xids = list((ctypes.c_ulong * count).from_address(children_p.value))
        xlib.XFree(ctypes.c_void_p(children_p.value))
        return xids
    except Exception:
        return []

# Pass --debug on the command line to enable per-frame capture diagnostics.
DEBUG_CAPTURE = "--debug" in os.sys.argv
IPC_DEBUG = os.environ.get("EVE_PREVIEW_IPC_DEBUG", "").lower() in ("1", "true", "yes", "on")

SELF_PID = os.getpid()
SCRIPT_BASENAME = os.path.basename(__file__)

def _proc_cmdline_contains(pid: int, needles):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read().replace(b"\x00", b" ")
        low = raw.lower()
        return any(n.encode("utf-8").lower() in low for n in needles)
    except Exception:
        return False

def _get_window_name(wnck_window):
    try:
        return (wnck_window.get_name() or "").strip()
    except Exception:
        return ""

def _looks_like_launcher(name, pid=0):
    low = (name or "").lower()
    if any(k in low for k in ("launcher", "eve launcher")):
        return True
    # NOTE: "qml" was removed from this list. It is only 3 characters and
    # produced false positives on real EVE client cmdlines whose ssoToken
    # values, paths, or other arguments happened to contain that substring.
    # "qtwebengine" alone is a specific enough launcher signature.
    if pid and _proc_cmdline_contains(pid, ["evelauncher", "launcher.exe", "qtwebengine"]):
        return True
    return False

def _is_real_eve_client_process(pid):
    if not pid:
        return False
    return _proc_cmdline_contains(pid, ["exefile.exe", "eve.exe", "steam_app_8500", "c_program_files_ccp_eve"])

def is_eve_window_steamaware(wnck_window):
    try:
        if wnck_window.get_pid() == SELF_PID:
            return False
    except Exception:
        pass
    pid = 0
    try:
        pid = wnck_window.get_pid() or 0
    except Exception:
        pid = 0
    name = _get_window_name(wnck_window)
    low = name.lower()
    if SCRIPT_BASENAME.lower() in low or "eve-o preview" in low:
        return False
    if not name:
        return False
    # Stable/fully resolved EVE client title — accept BEFORE any heuristic
    # rejection. "EVE - <CharacterName>" is unambiguous; the launcher never
    # uses this title, so this short-circuit is safe and protects real
    # clients from false-positive cmdline matches in _looks_like_launcher.
    if low.startswith("eve - ") and "launcher" not in low:
        return True
    if _looks_like_launcher(name, pid):
        return False
    if low in ("untitled window", "wine desktop"):
        return False
    # Do NOT add generic EVE windows yet. They frequently represent transient
    # startup/helper surfaces and are the source of the multi-client hang.
    # Let the pending name-changed watcher add them only after the title
    # resolves to the actual character name.
    if low in ("eve", "eve online"):
        return False
    # Last-resort process-based accept only when title is already non-generic.
    if _is_real_eve_client_process(pid):
        return True
    return False

class _PortalGlobalShortcuts:
    """xdg-desktop-portal GlobalShortcuts integration (Wayland-native).

    On Plasma 6 Wayland, third-party processes cannot reliably bind global
    shortcuts via the legacy kglobalaccel D-Bus API — kglobalaccel accepts
    the registration but KWin's keyboard input router doesn't pick it up.
    The supported third-party path is the freedesktop portal at
    ``org.freedesktop.portal.Desktop`` interface
    ``org.freedesktop.portal.GlobalShortcuts``.

    Flow (all asynchronous, gated on Response signals):
      1. CreateSession → portal returns a request object; on Response the
         results contain ``session_handle``.
      2. BindShortcuts(session, [(id, props), …]) → portal shows the
         "Allow this app to bind …?" dialog. On Response the bindings are
         live.
      3. Subscribe to ``Activated(session, id, timestamp, options)``.
      4. On press, dispatch ``on_pressed(slot:int)`` from the GTK main loop.

    Session lifetime is process-bound. Binding-list changes during the
    session (slots opening/closing) are batched via ``set_desired_shortcuts``
    + ``rebind`` — the portal does not currently support incremental
    add/remove on an existing session, so rebind reissues the whole set.
    """

    SERVICE = "org.freedesktop.portal.Desktop"
    PATH = "/org/freedesktop/portal/desktop"
    IFACE = "org.freedesktop.portal.GlobalShortcuts"
    REQ_IFACE = "org.freedesktop.portal.Request"

    def __init__(self, on_pressed, on_state_change=None):
        from gi.repository import Gio as _Gio
        self._Gio = _Gio
        self._on_pressed = on_pressed
        self._on_state_change = on_state_change or (lambda _s: None)
        self._bus = _Gio.bus_get_sync(_Gio.BusType.SESSION, None)

        # Probe — raises on non-portal setups.
        self._bus.call_sync(
            self.SERVICE, self.PATH, "org.freedesktop.DBus.Peer", "Ping",
            None, None, _Gio.DBusCallFlags.NONE, 2000, None,
        )

        unique = self._bus.get_unique_name() or ""
        self._sender_path = unique.lstrip(":").replace(".", "_")

        self._session_handle = None
        self._activated_sub = None
        self._desired = []   # list of (id_str, label_str, preferred_trigger_str)
        self._bound_ids = set()
        self._state = "idle"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def state(self):
        return self._state

    def bound_ids(self):
        return set(self._bound_ids)

    def set_desired_shortcuts(self, shortcuts):
        """shortcuts: iterable of (shortcut_id, description, preferred_trigger)."""
        self._desired = [tuple(s) for s in shortcuts]

    def start(self):
        """Kick off CreateSession → BindShortcuts → Subscribe."""
        if self._state not in ("idle", "error"):
            return
        self._set_state("creating-session")
        self._create_session()

    def stop(self):
        """Tear down the session and signal subscription."""
        if self._activated_sub is not None:
            try:
                self._bus.signal_unsubscribe(self._activated_sub)
            except Exception:
                pass
            self._activated_sub = None
        if self._session_handle is not None:
            try:
                self._bus.call_sync(
                    self.SERVICE, self._session_handle,
                    "org.freedesktop.portal.Session", "Close",
                    None, None, self._Gio.DBusCallFlags.NONE, 2000, None,
                )
            except Exception:
                pass
            self._session_handle = None
        self._bound_ids = set()
        self._set_state("idle")

    def rebind(self):
        """Reissue BindShortcuts with the current _desired list. No-op until
        the session is active."""
        if self._session_handle is None:
            return
        self._set_state("binding-shortcuts")
        self._bind_shortcuts()

    def purge_kde_bindings(self, kglobalaccel_component="eve_o_preview"):
        """Wipe the component's persisted shortcuts from KDE's kglobalaccel
        store. Without this, ``BindShortcuts`` on the next launch sees the
        existing IDs in ``kglobalshortcutsrc`` and reuses them silently — so
        clicking Register after Unregister would never re-prompt for new
        triggers. ``cleanUp`` removes the component entirely; the next bind
        re-creates it with a fresh permission dialog."""
        try:
            self._bus.call_sync(
                "org.kde.kglobalaccel",
                f"/component/{kglobalaccel_component}",
                "org.kde.kglobalaccel.Component", "cleanUp",
                None, None, self._Gio.DBusCallFlags.NONE, 5000, None,
            )
            print(f"[portal] kglobalaccel component '{kglobalaccel_component}' cleaned")
        except Exception as e:
            # Non-KDE environments won't have kglobalaccel. Swallow.
            print(f"[portal] kglobalaccel cleanup skipped: {e}")

    # ------------------------------------------------------------------
    # Internal: state + tokens
    # ------------------------------------------------------------------
    def _set_state(self, s):
        self._state = s
        try:
            self._on_state_change(s)
        except Exception:
            pass

    def _gen_token(self, prefix):
        import secrets
        return f"{prefix}_{secrets.token_hex(6)}"

    def _request_path(self, handle_token):
        return f"/org/freedesktop/portal/desktop/request/{self._sender_path}/{handle_token}"

    @staticmethod
    def _vardict(d):
        """Build a GVariant of type a{sv} from a Python dict {str: Variant}.
        PyGObject's `GLib.Variant('a{sv}', d)` constructor raises KeyError(0)
        when values are Variants — VariantBuilder avoids that ambiguity."""
        builder = GLib.VariantBuilder.new(GLib.VariantType("a{sv}"))
        for k, v in d.items():
            builder.add_value(GLib.Variant("{sv}", (k, v)))
        return builder.end()

    @staticmethod
    def _shortcut_array(entries):
        """Build a GVariant of type a(sa{sv}) for BindShortcuts.

        ``entries`` is a list of (id_str, props_dict_of_variants).
        """
        builder = GLib.VariantBuilder.new(GLib.VariantType("a(sa{sv})"))
        for sid, props in entries:
            props_builder = GLib.VariantBuilder.new(GLib.VariantType("a{sv}"))
            for k, v in props.items():
                props_builder.add_value(GLib.Variant("{sv}", (k, v)))
            tup = GLib.Variant.new_tuple(
                GLib.Variant("s", sid),
                props_builder.end(),
            )
            builder.add_value(tup)
        return builder.end()

    def _subscribe_response(self, handle_token, on_response):
        """Subscribe to the Response signal for a specific request path.
        Returns the subscription id. The handler is responsible for
        unsubscribing once done."""
        path = self._request_path(handle_token)
        return self._bus.signal_subscribe(
            None, self.REQ_IFACE, "Response", path, None,
            self._Gio.DBusSignalFlags.NONE, on_response,
        )

    # ------------------------------------------------------------------
    # Step 1: CreateSession
    # ------------------------------------------------------------------
    def _create_session(self):
        handle_token = self._gen_token("evepreview_cs")
        session_token = self._gen_token("evepreview_session")

        sub_holder = [None]
        def on_response(_conn, _sender, _path, _iface, _signal, params):
            if sub_holder[0] is not None:
                try:
                    self._bus.signal_unsubscribe(sub_holder[0])
                except Exception:
                    pass
                sub_holder[0] = None
            try:
                response_code, results = params.unpack()
            except Exception as e:
                print(f"[portal] CreateSession response unpack failed: {e}")
                self._set_state("error: response unpack")
                return
            if response_code != 0:
                print(f"[portal] CreateSession refused (code {response_code})")
                self._set_state(f"error: CreateSession code {response_code}")
                return
            self._session_handle = results.get("session_handle") \
                or f"/org/freedesktop/portal/desktop/session/{self._sender_path}/{session_token}"
            print(f"[portal] session = {self._session_handle}")
            self._subscribe_activated()
            self._set_state("binding-shortcuts")
            self._bind_shortcuts()

        sub_holder[0] = self._subscribe_response(handle_token, on_response)

        options = self._vardict({
            "handle_token": GLib.Variant("s", handle_token),
            "session_handle_token": GLib.Variant("s", session_token),
        })
        try:
            self._bus.call_sync(
                self.SERVICE, self.PATH, self.IFACE, "CreateSession",
                GLib.Variant.new_tuple(options),
                None, self._Gio.DBusCallFlags.NONE, 5000, None,
            )
        except Exception as e:
            print(f"[portal] CreateSession call failed: {e}")
            if sub_holder[0] is not None:
                try:
                    self._bus.signal_unsubscribe(sub_holder[0])
                except Exception:
                    pass
            self._set_state(f"error: {e}")

    # ------------------------------------------------------------------
    # Step 2: BindShortcuts
    # ------------------------------------------------------------------
    def _bind_shortcuts(self):
        if self._session_handle is None or not self._desired:
            self._bound_ids = set()
            self._set_state("idle" if not self._desired else "no-session")
            return

        handle_token = self._gen_token("evepreview_bs")

        # Build shortcut array: a(sa{sv})
        shortcut_entries = []
        for shortcut_id, description, preferred in self._desired:
            props = {
                "description": GLib.Variant("s", description),
            }
            if preferred:
                props["preferred_trigger"] = GLib.Variant("s", preferred)
            shortcut_entries.append((shortcut_id, props))

        shortcuts_variant = self._shortcut_array(shortcut_entries)

        sub_holder = [None]
        def on_response(_conn, _sender, _path, _iface, _signal, params):
            if sub_holder[0] is not None:
                try:
                    self._bus.signal_unsubscribe(sub_holder[0])
                except Exception:
                    pass
                sub_holder[0] = None
            try:
                response_code, results = params.unpack()
            except Exception as e:
                print(f"[portal] BindShortcuts response unpack failed: {e}")
                self._set_state("error: bind response unpack")
                return
            if response_code != 0:
                print(f"[portal] BindShortcuts refused (code {response_code})")
                self._set_state(f"error: BindShortcuts code {response_code}")
                return
            shortcuts = results.get("shortcuts", []) or []
            self._bound_ids = {s[0] for s in shortcuts}
            print(f"[portal] bound: {sorted(self._bound_ids)}")
            self._set_state("active")

        sub_holder[0] = self._subscribe_response(handle_token, on_response)

        options = self._vardict({
            "handle_token": GLib.Variant("s", handle_token),
        })
        try:
            self._bus.call_sync(
                self.SERVICE, self.PATH, self.IFACE, "BindShortcuts",
                GLib.Variant.new_tuple(
                    GLib.Variant("o", self._session_handle),
                    shortcuts_variant,
                    GLib.Variant("s", ""),  # parent_window — unused
                    options,
                ),
                None, self._Gio.DBusCallFlags.NONE, 5000, None,
            )
        except Exception as e:
            print(f"[portal] BindShortcuts call failed: {e}")
            if sub_holder[0] is not None:
                try:
                    self._bus.signal_unsubscribe(sub_holder[0])
                except Exception:
                    pass
            self._set_state(f"error: {e}")

    # ------------------------------------------------------------------
    # Step 3: Activated signal subscription
    # ------------------------------------------------------------------
    def _subscribe_activated(self):
        if self._activated_sub is not None:
            return
        self._activated_sub = self._bus.signal_subscribe(
            None, self.IFACE, "Activated", self.PATH, None,
            self._Gio.DBusSignalFlags.NONE, self._on_activated,
        )
        print(f"[portal] subscribed to Activated (sub_id={self._activated_sub})")

    def _on_activated(self, _conn, sender, path, iface, signal, params):
        try:
            session_handle, shortcut_id, _timestamp, _options = params.unpack()
        except Exception as e:
            print(f"[portal] Activated unpack failed: {e}")
            return
        if self._session_handle is not None and session_handle != self._session_handle:
            return  # different session — not for us
        GLib.idle_add(self._on_pressed, shortcut_id)


class _ThumbnailItem(Gtk.Box):
    """One thumbnail inside the ThumbnailDock.

    Mirrors the captured pixbuf from its source ThumbnailWindow (which keeps
    running the capture pipeline as before but is never shown). Click to
    activate the underlying EVE client; updates the label when the
    character name changes.
    """

    def __init__(self, xid, source_thumb, on_activate, config):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.xid = xid
        self.source_thumb = source_thumb
        self.on_activate = on_activate
        self.config = config
        self.is_active = False
        self._poll_id = None
        # Current slot binding for sort ordering. 0 = unassigned (sorts to
        # end). Updated by ThumbnailDock.update_slot_order().
        self.slot = 0

        # Image container with optional active-state CSS border
        self.frame = Gtk.Frame()
        self.frame.set_shadow_type(Gtk.ShadowType.NONE)
        evbox = Gtk.EventBox()
        evbox.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        evbox.connect("button-press-event", self._on_click)
        self.image = Gtk.Image()
        w = int(config.settings.get("thumbnail_width", 320))
        h = int(config.settings.get("thumbnail_height", 200))
        self.image.set_size_request(w, h)
        evbox.add(self.image)
        self.frame.add(evbox)
        self.pack_start(self.frame, True, True, 0)

        self.label = Gtk.Label()
        self.label.set_halign(Gtk.Align.CENTER)
        self.pack_start(self.label, False, False, 0)
        self.update_label_from_window()
        self._update_border_style()

        # Mirror the captured frame ~20 Hz; ThumbnailWindow's tick() is the
        # real capture loop, we just snapshot its current pixbuf.
        self._poll_id = GLib.timeout_add(50, self._sync_frame)

    def _on_click(self, _widget, event):
        if event.button == 1:
            self.on_activate(self.source_thumb.wnck_window)
        return False

    def _sync_frame(self):
        try:
            pb = self.source_thumb.image.get_pixbuf()
            if pb is not None:
                self.image.set_from_pixbuf(pb)
        except Exception:
            pass
        return True

    def update_label_from_window(self):
        raw = self.source_thumb.wnck_window.get_name() or "EVE"
        if " - " in raw:
            raw = raw.split(" - ", 1)[1].split("[")[0].strip()
        self.label.set_markup(f"<b>{GLib.markup_escape_text(raw)}</b>")

    def set_active(self, is_active):
        self.is_active = is_active
        self._update_border_style()

    def _update_border_style(self):
        # 3 px border in active color when active, transparent otherwise.
        color = self.config.settings.get("active_border_color", "#00FF00")
        ctx = self.frame.get_style_context()
        cls = "eve-thumb-active"
        if not hasattr(_ThumbnailItem, "_css_loaded"):
            _ThumbnailItem._css_loaded = True
        # Install a per-widget style provider (cheap; one per item)
        prov = Gtk.CssProvider()
        css = f".eve-thumb-active {{ border: 3px solid {color}; }} " \
              f".eve-thumb-inactive {{ border: 3px solid transparent; }}"
        try:
            prov.load_from_data(css.encode("utf-8"))
            ctx.add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except Exception:
            pass
        if self.is_active:
            ctx.add_class("eve-thumb-active")
            ctx.remove_class("eve-thumb-inactive")
        else:
            ctx.add_class("eve-thumb-inactive")
            ctx.remove_class("eve-thumb-active")

    def destroy(self):
        if self._poll_id is not None:
            try:
                GLib.source_remove(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        super().destroy()


class ThumbnailDock(Gtk.Window):
    """Single resizable container window for all thumbnails.

    Uses a Gtk.FlowBox so the number of columns adapts automatically as the
    window is resized. Position and size persist to the app config.
    """

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.items = {}    # xid → _ThumbnailItem
        self._save_timer = None

        self.set_title("EVE-O Thumbnails")
        self.set_decorated(True)
        self.set_skip_taskbar_hint(False)
        self.set_keep_above(bool(self.config.settings.get("always_on_top", True)))
        try:
            self.set_opacity(float(self.config.settings.get("opacity", 0.95)))
        except Exception:
            pass

        # Restore last size/position
        size = self.config.settings.get("dock_size") or [680, 260]
        try:
            self.set_default_size(int(size[0]), int(size[1]))
        except Exception:
            self.set_default_size(680, 260)
        pos = self.config.settings.get("dock_position")
        if pos:
            try:
                self.move(int(pos[0]), int(pos[1]))
            except Exception:
                pass

        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_homogeneous(True)
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_min_children_per_line(1)
        self.flow.set_max_children_per_line(20)
        self.flow.set_column_spacing(6)
        self.flow.set_row_spacing(6)
        self.flow.set_margin_top(6)
        self.flow.set_margin_bottom(6)
        self.flow.set_margin_start(6)
        self.flow.set_margin_end(6)
        # Keep items ordered by slot number — without this, removing a
        # middle item and re-adding it later leaves gaps and out-of-order
        # neighbours. Items with slot=0 (unassigned) sort to the end.
        self.flow.set_sort_func(self._sort_by_slot, None)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.add(self.flow)
        self.add(scrolled)

        # Closing dock doesn't quit the app — just hide.
        self.connect("delete-event", lambda *_: (self.hide(), True)[1])
        self.connect("configure-event", self._on_configure)

    def _on_configure(self, _w, _ev):
        # Debounced save of geometry to config.
        try:
            x, y = self.get_position()
            w, h = self.get_size()
            self.config.settings["dock_position"] = [x, y]
            self.config.settings["dock_size"] = [w, h]
        except Exception:
            return False
        if self._save_timer is not None:
            try:
                GLib.source_remove(self._save_timer)
            except Exception:
                pass
        self._save_timer = GLib.timeout_add(400, self._save_geometry)
        return False

    def _save_geometry(self):
        self._save_timer = None
        try:
            self.config.save()
        except Exception:
            pass
        return False

    def add_thumb(self, xid, source_thumb, on_activate):
        if xid in self.items:
            return self.items[xid]
        item = _ThumbnailItem(xid, source_thumb, on_activate, self.config)
        self.items[xid] = item
        self.flow.add(item)
        item.show_all()
        if not self.get_visible():
            self.show_all()
        return item

    def remove_thumb(self, xid):
        item = self.items.pop(xid, None)
        if item is None:
            return
        try:
            item.destroy()
        except Exception:
            pass
        if not self.items:
            self.hide()

    def set_active(self, active_xid):
        for xid, item in self.items.items():
            item.set_active(xid == active_xid)

    def refresh_labels(self):
        for item in self.items.values():
            try:
                item.update_label_from_window()
            except Exception:
                pass

    @staticmethod
    def _sort_by_slot(c1, c2, _data):
        i1 = c1.get_child()
        i2 = c2.get_child()
        s1 = getattr(i1, "slot", 0) or 999
        s2 = getattr(i2, "slot", 0) or 999
        if s1 != s2:
            return -1 if s1 < s2 else 1
        # Tiebreak on xid so order is stable when both are unassigned.
        x1 = getattr(i1, "xid", 0)
        x2 = getattr(i2, "xid", 0)
        return -1 if x1 < x2 else (1 if x1 > x2 else 0)

    def update_slot_order(self, bindings):
        """Apply current slot bindings (slot_str → {xid, …}) to items so
        the FlowBox can re-sort. Call after every _write_slots_state."""
        xid_to_slot = {}
        for slot_str, info in (bindings or {}).items():
            try:
                xid_to_slot[int(info["xid"], 16)] = int(slot_str)
            except (TypeError, ValueError, KeyError):
                continue
        changed = False
        for xid, item in self.items.items():
            new_slot = xid_to_slot.get(xid, 0)
            if item.slot != new_slot:
                item.slot = new_slot
                changed = True
        if changed:
            self.flow.invalidate_sort()


class Config:
    def __init__(self):
        from pathlib import Path as _Path
        self.config_dir = _Path.home() / ".config" / "eve-o-preview-linux"
        self.config_file = self.config_dir / "config.json"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.default_config = {
            "thumbnail_width": 320,
            "thumbnail_height": 200,
            "opacity": 0.95,
            "always_on_top": True,
            "hide_active_client": False,
            "zoom_on_hover": True,
            "zoom_factor": 1.25,
            "show_overlay": True,
            "refresh_fps": 10,  # FPS instead of period
            "active_border_color": "#00FF00",  # Neon green default
            "thumbnail_positions": {},
            # Hotkey slot assignment: maps character_name → preferred slot int (1-9).
            # When enabled, the app registers Meta+<slot> via kglobalaccel when
            # each EVE client appears and unregisters on close/exit. The slots.json
            # state file is still written for use by external tools like eve-switch.
            "slot_assignments": {},
            "max_hotkey_slots": 9,
            "kde_hotkeys_enabled": True,
            # Set to True after the first successful portal BindShortcuts call.
            # Drives the auto-rebind on next launch: KDE persists the user's
            # chosen triggers in kglobalshortcutsrc, but they fire only while a
            # portal session is actively bound to them. Without this flag we'd
            # have to choose between (a) surprising fresh installs with a
            # permission dialog or (b) forcing every launch to click Register.
            "kde_hotkeys_registered": False,
            # Dock mode: all thumbnails live inside a single resizable window
            # with a flow layout that adapts row/column count to width. When
            # off, each thumbnail is its own floating window (legacy behavior).
            "dock_mode": False,
            "dock_position": None,
            "dock_size": [680, 260],
        }
        self.slots_file = self.config_dir / "slots.json"
        self.settings = self.load()

    def load(self):
        try:
            if self.config_file.exists():
                with open(self.config_file, "r") as f:
                    data = json.load(f)
                merged = self.default_config.copy()
                merged.update(data)
                return merged
        except Exception as e:
            print("Config load error:", e)
        return self.default_config.copy()

    def save(self):
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print("Config save error:", e)

class ThumbnailWindow(Gtk.Window):
    def __init__(self, wnck_window, config, on_activate_callback):
        super().__init__()
        self.wnck_window = wnck_window
        self.config = config
        self.on_activate_callback = on_activate_callback

        self.original_size = (config.settings["thumbnail_width"],
                              config.settings["thumbnail_height"])
        self.is_hovering = False
        self.is_active = False
        self.live_window = None
        self.update_id = None
        self._root_xid = None
        self._capture_xid = None
        self._target_w, self._target_h = self.original_size

        # Layer-shell mode: display via a Wayland OVERLAY subprocess.
        # This guarantees thumbnails appear above every fullscreen/fixed-window
        # surface because the Wayland compositor renders OVERLAY above all managed
        # windows unconditionally, regardless of XWayland stacking tricks.
        # NB: Disabled when the user has dock mode on — the captured pixbuf
        # then needs to live in self.image so the ThumbnailDock items can
        # mirror it. (Layer-shell mode ships frames to a subprocess instead.)
        self._use_ls = (
            _LAYER_SHELL_AVAILABLE and _WAYLAND_SESSION
            and not config.settings.get("dock_mode", False)
        )
        self._ls = None       # _LayerShellDisplay, created after GTK init
        self._ls_x = self._ls_y = 0

        # GTK window setup (still needed for the capture machinery and as a
        # controller object; the window itself is NOT shown in layer-shell mode).
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(not self._use_ls)
        self.set_decorated(False)
        self._always_on_top = self.config.settings.get("always_on_top", True)
        if self._always_on_top and not self._use_ls:
            self.set_keep_above(True)
        self.connect("realize", self._on_realize)
        self.connect("map", self._on_map)
        try:
            self.set_opacity(self.config.settings.get("opacity", 0.95))
        except Exception:
            pass
        self.set_default_size(*self.original_size)

        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)

        # Create a frame for the border effect
        self.border_frame = Gtk.Frame()
        self.border_frame.set_shadow_type(Gtk.ShadowType.NONE)
        self.add(self.border_frame)
        
        self.overlay = Gtk.Overlay()
        self.border_frame.add(self.overlay)
        self.image = Gtk.Image()
        self.overlay.add(self.image)
        
        # Apply initial border style
        self._update_border_style()

        # Always create the label for character name
        self.label = Gtk.Label()
        title = self.wnck_window.get_name() or "EVE"
        # Extract character name from window title (format: "EVE - Character Name")
        if " - " in title:
            char_name = title.split(" - ", 1)[1]
            # Remove any trailing parts like " [Omega]" or similar
            if "[" in char_name:
                char_name = char_name.split("[")[0].strip()
            title = char_name
        self.label.set_markup(f"<b>{title}</b>")
        self.label.set_halign(Gtk.Align.CENTER)
        self.label.set_valign(Gtk.Align.START)
        css = Gtk.CssProvider()
        css.load_from_data(b"label { background: rgba(0,0,0,0.7); color: white; padding: 6px 10px; margin: 6px; border-radius: 3px; font-size: 11px; }")
        self.label.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        
        if self.config.settings.get("show_overlay", True):
            self.overlay.add_overlay(self.label)
        else:
            self.label.set_no_show_all(True)
            self.label.hide()

        # click/drag logic
        self._press_pos = None
        self._dragging = False
        self._drag_threshold = 6

        self.add_events(
            Gdk.EventMask.ENTER_NOTIFY_MASK |
            Gdk.EventMask.LEAVE_NOTIFY_MASK |
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.connect("button-press-event", self._on_button_press)
        self.connect("button-release-event", self._on_button_release)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("enter-notify-event", self._on_mouse_enter)
        self.connect("leave-notify-event", self._on_mouse_leave)
        self.connect("destroy", self._on_destroy)

        # restore position
        name = self.wnck_window.get_name()
        pos = self.config.settings.get("thumbnail_positions", {}).get(name)
        if pos:
            self._ls_x, self._ls_y = int(pos[0]), int(pos[1])

        # Create the layer-shell subprocess now that GTK widget tree is built.
        # Position/size are sent after subprocess starts; the actual show() call
        # comes later from _add_thumb() via show_all().
        if self._use_ls:
            import time as _time_mod
            _last_click_time = [0.0]

            def _click():
                # Secondary debounce in the main process: in case the subprocess
                # debounce is bypassed (e.g. two subprocesses both firing CLICK),
                # reject calls arriving within 500 ms of the last activation.
                now = _time_mod.monotonic()
                if now - _last_click_time[0] < 0.5:
                    print(f"[click] debounced", flush=True)
                    return
                _last_click_time[0] = now
                # Use the XID actually being screenshotted (_capture_xid).  Wine/
                # Proton often opens an "Untitled window" parent that KWin doesn't
                # track; the real EVE content is in a child window found by
                # bind_live.  Activating the capture XID targets the visible surface.
                xid = getattr(self, "_capture_xid", None) or self.wnck_window.get_xid()
                name = self.wnck_window.get_name()
                print(f"[click] activating '{name}' xid=0x{xid:x} (capture={xid!=self.wnck_window.get_xid()})", flush=True)

                # Get a real X11 server timestamp — use for all activation methods.
                try:
                    _ts = GdkX11.x11_get_server_time(Gdk.get_default_root_window())
                except Exception:
                    _ts = 0

                # Unminimize first — wmctrl/xdotool exit=1 on minimized windows.
                try:
                    if self.wnck_window.is_minimized():
                        print(f"[click] unminimizing first", flush=True)
                        self.wnck_window.unminimize(_ts)
                except Exception as e:
                    print(f"[click] unminimize error: {e}", flush=True)

                # Map the X11 window if it's currently unmapped (EVE's loading
                # screen temporarily withdraws the XWayland surface). We must do
                # this BEFORE wmctrl/xdotool so they get a mapped window.
                xlib = _get_xlib()
                dpy  = _xlib_display()
                if xlib and dpy:
                    try:
                        xlib.XMapWindow.restype  = ctypes.c_int
                        xlib.XMapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
                        xlib.XMapWindow(ctypes.c_void_p(dpy), ctypes.c_ulong(xid))
                        xlib.XFlush.restype = ctypes.c_int
                        xlib.XFlush(ctypes.c_void_p(dpy))
                        print(f"[click] XMapWindow called", flush=True)
                    except Exception as e:
                        print(f"[click] XMapWindow error: {e}", flush=True)

                import subprocess as _sp
                # 1) wmctrl — plain activation request to KWin
                _wmctrl_ok = False
                try:
                    r = _sp.run(["wmctrl", "-ia", hex(xid)],
                                capture_output=True, timeout=2)
                    print(f"[click] wmctrl exit={r.returncode}", flush=True)
                    _wmctrl_ok = (r.returncode == 0)
                except FileNotFoundError:
                    print("[click] wmctrl not found", flush=True)
                except Exception as e:
                    print(f"[click] wmctrl error: {e}", flush=True)

                # 2) xdotool — often more reliable for XWayland windows
                #    (sudo dnf install xdotool / sudo apt install xdotool)
                _xdotool_ok = False
                try:
                    r = _sp.run(
                        ["xdotool", "windowactivate", "--sync", str(xid)],
                        capture_output=True, timeout=2)
                    print(f"[click] xdotool exit={r.returncode}", flush=True)
                    _xdotool_ok = (r.returncode == 0)
                except FileNotFoundError:
                    print("[click] xdotool not found (dnf install xdotool)", flush=True)
                except Exception as e:
                    print(f"[click] xdotool error: {e}", flush=True)

                if _wmctrl_ok or _xdotool_ok:
                    return

                # 2b) PID fallback: search for a sibling window from the same
                # process that KWin DOES manage (_NET_CLIENT_LIST).  Wine/Proton
                # at character-selection creates an "Untitled window" that KWin
                # doesn't track; another window from the same PID is the one
                # KWin can activate.
                if not _wmctrl_ok:
                    try:
                        target_pid = self.wnck_window.get_pid()
                        if target_pid:
                            for sibling in Wnck.Screen.get_default().get_windows():
                                s_xid = sibling.get_xid()
                                if s_xid == xid or sibling.get_pid() != target_pid:
                                    continue
                                s_name = sibling.get_name()
                                print(f"[click] trying PID sibling 0x{s_xid:x} '{s_name}'", flush=True)
                                r2 = _sp.run(["wmctrl", "-ia", hex(s_xid)],
                                             capture_output=True, timeout=2)
                                print(f"[click] sibling wmctrl exit={r2.returncode}", flush=True)
                                if r2.returncode == 0:
                                    _wmctrl_ok = True
                                    break
                    except Exception as e:
                        print(f"[click] sibling search: {e}", flush=True)

                if _wmctrl_ok:
                    return

                # 3) Direct Xlib _NET_ACTIVE_WINDOW + XSetInputFocus
                ok = _net_activate_window(xid, _ts)
                print(f"[click] _net_activate_window={ok}", flush=True)
                # 4) Wnck fallback
                try:
                    print(f"[click] Wnck activate ts={_ts}", flush=True)
                    if self.wnck_window.is_minimized():
                        self.wnck_window.unminimize(_ts)
                    self.wnck_window.activate(_ts)
                except Exception as e:
                    print(f"[click] Wnck error: {e}", flush=True)

            def _ctrl_click():
                try:
                    self.wnck_window.minimize()
                except Exception:
                    pass

            # Zoom debounce state — shared across _enter/_leave closures.
            _leave_timer = [None]

            def _enter():
                if not self.config.settings.get("zoom_on_hover", True):
                    return
                if _leave_timer[0]:
                    GLib.source_remove(_leave_timer[0])
                    _leave_timer[0] = None
                if not self.is_hovering:
                    self.is_hovering = True
                    z = self.config.settings.get("zoom_factor", 1.25)
                    zw = int(self.original_size[0] * z)
                    zh = int(self.original_size[1] * z)
                    # Update capture size so frames render at zoomed resolution
                    self._target_w, self._target_h = zw, zh
                    if self._ls:
                        self._ls.set_size(zw, zh)

            def _leave():
                if not self.config.settings.get("zoom_on_hover", True):
                    return
                if _leave_timer[0]:
                    GLib.source_remove(_leave_timer[0])
                def _do_leave():
                    _leave_timer[0] = None
                    if self.is_hovering:
                        self.is_hovering = False
                        self._target_w, self._target_h = self.original_size
                        if self._ls:
                            self._ls.set_size(*self.original_size)
                _leave_timer[0] = GLib.timeout_add(80, _do_leave)

            self._ls = _LayerShellDisplay(
                self._ls_x, self._ls_y,
                self._target_w, self._target_h,
                _click, _ctrl_click, self._on_ls_pos,
                _enter, _leave,
            )
            self._ls_save_timer = None

            def _send_title():
                if not self._ls or not self.config.settings.get("show_overlay", True):
                    return
                raw = self.wnck_window.get_name() or ""
                # EVE window title format: "EVE - CharacterName" or just "EVE"
                # Extract everything after the first " - "
                if " - " in raw:
                    title = raw.split(" - ", 1)[1].split("[")[0].strip()
                else:
                    title = raw
                self._ls.send_title(title)

            _send_title()
            # Update label whenever EVE finishes loading the character.
            self.wnck_window.connect("name-changed", lambda *_: _send_title())
            # Fallback poll: EVE may update its title AFTER name-changed fires
            # (or not fire it at all on some Wine versions). Retry for 60s.
            _poll_count = [0]
            def _poll_title():
                _poll_count[0] += 1
                _send_title()
                return _poll_count[0] < 20  # stop after 20 * 3s = 60s
            GLib.timeout_add(3000, _poll_title)

    # ------------------------------------------------------------------
    # Layer-shell delegation — override GTK.Window methods so callers
    # in EVEOPreview don't need to know which display mode is active.
    # ------------------------------------------------------------------

    def show(self):
        if self._use_ls:
            if self._ls:
                self._ls.show()
        else:
            super().show()

    def show_all(self):
        if self._use_ls:
            if self._ls:
                self._ls.show()
        else:
            super().show_all()

    def hide(self):
        if self._use_ls:
            if self._ls:
                self._ls.hide()
        else:
            super().hide()

    def move(self, x, y):
        self._ls_x, self._ls_y = x, y
        if self._use_ls:
            if self._ls:
                self._ls.set_pos(x, y)
        else:
            super().move(x, y)

    def resize(self, w, h):
        self._target_w, self._target_h = w, h
        if self._use_ls:
            if self._ls:
                self._ls.set_size(w, h)
        else:
            super().resize(w, h)

    def set_keep_above(self, above):
        if not self._use_ls:
            super().set_keep_above(above)
        # Layer-shell OVERLAY is unconditionally above everything; no-op here.

    def destroy(self):
        if self._use_ls:
            # Save position before destroying subprocess
            try:
                name = self.wnck_window.get_name()
                cfg = self.config.settings.setdefault("thumbnail_positions", {})
                cfg[name] = [self._ls_x, self._ls_y]
                self.config.save()
            except Exception:
                pass
            if self._ls:
                self._ls.destroy()
            if self.update_id:
                try:
                    GLib.source_remove(self.update_id)
                except Exception:
                    pass
                self.update_id = None
        else:
            super().destroy()

    def _on_ls_pos(self, x, y):
        """Called when the layer-shell subprocess reports a drag-move."""
        self._ls_x, self._ls_y = x, y
        # Debounce config saves: writing JSON on every motion event blocks the
        # GLib main loop and causes frame drops / visual stutter during drag.
        if hasattr(self, '_ls_save_timer') and self._ls_save_timer:
            GLib.source_remove(self._ls_save_timer)
        self._ls_save_timer = GLib.timeout_add(400, self._save_ls_pos)

    def _save_ls_pos(self):
        self._ls_save_timer = None
        try:
            name = self.wnck_window.get_name()
            cfg = self.config.settings.setdefault("thumbnail_positions", {})
            cfg[name] = [self._ls_x, self._ls_y]
            self.config.save()
        except Exception:
            pass
        return False  # don't repeat

    # ------------------------------------------------------------------

    def _on_realize(self, widget):
        if self._always_on_top and not self._use_ls:
            self.set_keep_above(True)

    def _on_map(self, widget):
        """Re-assert after map — KWin processes _NET_WM_STATE changes post-map."""
        if self._always_on_top and not self._use_ls:
            super().set_keep_above(True)
            gdk_win = self.get_window()
            if gdk_win:
                gdk_win.raise_()

    def bind_live(self, xid, target_w, target_h):
        try:
            display = GdkX11.X11Display.get_default()
            if not display:
                raise RuntimeError("No X11 display for GdkX11")
            self._root_xid = xid
            self._capture_xid = xid          # may be replaced by child in tick
            self.live_window = GdkX11.X11Window.foreign_new_for_display(display, xid)
            self._target_w, self._target_h = int(target_w), int(target_h)
            self._start_live_timer()
        except Exception as e:
            print("Live capture bind failed:", e)

    def _start_live_timer(self):
        if self.update_id:
            try:
                GLib.source_remove(self.update_id)
            except Exception:
                pass
            self.update_id = None
        
        # Convert FPS to milliseconds
        fps = int(self.config.settings.get("refresh_fps", 10))
        period = int(1000 / fps)  # Convert FPS to ms

        # Rate-limit _try_bind_child: at most once per second, not every tick.
        _child_bind_counter = [0]
        _child_bind_interval = max(fps, 10)  # try once per second

        def _try_bind_child():
            """Wine Fixed Window renders into a child XID — find and bind it."""
            try:
                display = GdkX11.X11Display.get_default()
                children = _get_child_xids(self._root_xid)
                if DEBUG_CAPTURE:
                    print(f"[capture] XID=0x{self._root_xid:x} children={[hex(c) for c in children]}")
                for child_xid in reversed(children):   # last = topmost
                    cw = GdkX11.X11Window.foreign_new_for_display(display, child_xid)
                    if cw:
                        cw_w, cw_h = cw.get_width(), cw.get_height()
                        if DEBUG_CAPTURE:
                            print(f"[capture]   child 0x{child_xid:x} size={cw_w}x{cw_h}")
                        if cw_w > 0 and cw_h > 0:
                            self.live_window   = cw
                            self._capture_xid  = child_xid
                            return True
            except Exception as e:
                if DEBUG_CAPTURE:
                    print(f"[capture] _try_bind_child error: {e}")
            return False

        _raise_counter = [0]

        # NOTE: tick takes *_args because GLib.Source.set_callback passes
        # user_data as an extra positional argument to the callback.
        def tick(*_args):
            if not self.live_window:
                return False
            # Re-assert window stacking every ~2 s (every 20 ticks at 10 fps).
            _raise_counter[0] += 1
            if _raise_counter[0] >= 20:
                _raise_counter[0] = 0
                if self._always_on_top:
                    self.set_keep_above(True)
                    gdk_win = self.get_window()
                    if gdk_win:
                        gdk_win.raise_()
            try:
                if self.wnck_window.is_minimized():
                    self._set_icon_fallback()
                    return True
            except Exception:
                pass
            try:
                w = self.live_window.get_width()
                h = self.live_window.get_height()
                if DEBUG_CAPTURE:
                    print(f"[capture] XID=0x{self._capture_xid:x} size={w}x{h}", end="")
                if w <= 0 or h <= 0:
                    if DEBUG_CAPTURE: print(" → invalid size, fallback")
                    self._set_icon_fallback()
                    return True
                # Skip non-viewable windows to avoid Gdk-CRITICAL spam.
                if not self.live_window.is_viewable():
                    self._set_icon_fallback()
                    return True
                Gdk.error_trap_push()
                pb = Gdk.pixbuf_get_from_window(self.live_window, 0, 0, w, h)
                if Gdk.error_trap_pop():
                    pb = None  # BadDrawable / window gone — ignore
                if DEBUG_CAPTURE:
                    print(f" → pixbuf={'ok' if pb else 'None'}")
                if pb:
                    pb = pb.scale_simple(self._target_w, self._target_h, GdkPixbuf.InterpType.BILINEAR)
                    if self._use_ls and self._ls:
                        self._ls.send_frame(pb)
                    else:
                        self.image.set_from_pixbuf(pb)
                else:
                    # Parent returned no pixels — try child windows (Wine Fixed Window)
                    # Rate-limited: once per second instead of every tick to avoid
                    # X11 round-trip storms with multiple clients.
                    _child_bind_counter[0] += 1
                    if self._capture_xid == self._root_xid and _child_bind_counter[0] >= _child_bind_interval:
                        _child_bind_counter[0] = 0
                        _try_bind_child()
                    self._set_icon_fallback()
            except Exception as e:
                if DEBUG_CAPTURE:
                    print(f"[capture] tick exception: {e}")
                self._set_icon_fallback()
            return True

        # CRITICAL: Use GLib.PRIORITY_LOW (300) for capture timers so they yield
        # to user input events (PRIORITY_DEFAULT=0) and IPC callbacks
        # (PRIORITY_HIGH=-100).  With two EVE clients, two capture timers at
        # PRIORITY_DEFAULT consume the entire main loop, starving idle_add
        # callbacks that deliver CLICK/ENTER/LEAVE from subprocesses.
        src = GLib.timeout_source_new(period)
        src.set_priority(GLib.PRIORITY_LOW)
        src.set_callback(tick)
        self.update_id = src.attach()

    def _set_icon_fallback(self):
        try:
            pixbuf = self.wnck_window.get_icon()
            if pixbuf:
                scaled = pixbuf.scale_simple(self._target_w, self._target_h, GdkPixbuf.InterpType.BILINEAR)
                self.image.set_from_pixbuf(scaled)
        except Exception:
            pass

    def _update_border_style(self):
        """Update the border color based on active state"""
        css = Gtk.CssProvider()
        if self.is_active:
            border_color = self.config.settings.get("active_border_color", "#00FF00")
            css_data = f"""
            frame {{
                border: 4px solid {border_color};
                border-radius: 4px;
            }}
            frame > border {{
                background-color: transparent;
            }}
            """.encode()
        else:
            css_data = b"""
            frame {
                border: 2px solid rgba(60, 60, 60, 0.5);
                border-radius: 2px;
            }
            frame > border {
                background-color: transparent;
            }
            """
        css.load_from_data(css_data)
        self.border_frame.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def set_active_state(self, is_active):
        """Set whether this thumbnail represents the active window"""
        if self.is_active != is_active:
            self.is_active = is_active
            if self._use_ls:
                if self._ls:
                    color = self.config.settings.get("active_border_color", "#00FF00")
                    self._ls.send_active(is_active, color)
            else:
                self._update_border_style()

    def _on_button_press(self, _w, event):
        if event.button == 1:
            if event.state & Gdk.ModifierType.CONTROL_MASK:
                try:
                    self.wnck_window.minimize()
                except Exception:
                    pass
                return True
            self._press_pos = (event.x_root, event.y_root, event.time)
            self._dragging = False
            return True
        if event.button == 3:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
            return True
        return False

    def _on_motion(self, _w, event):
        if not self._press_pos:
            return False
        dx = abs(event.x_root - self._press_pos[0])
        dy = abs(event.y_root - self._press_pos[1])
        if not self._dragging and (dx > self._drag_threshold or dy > self._drag_threshold):
            self._dragging = True
            self.begin_move_drag(1, int(self._press_pos[0]), int(self._press_pos[1]), int(self._press_pos[2]))
            return True
        return False

    def _on_button_release(self, _w, event):
        if event.button == 1:
            if not self._dragging:
                try:
                    if self.wnck_window.is_minimized():
                        self.wnck_window.unminimize(Gtk.get_current_event_time())
                    self.on_activate_callback(self.wnck_window)
                except Exception:
                    pass
            self._press_pos = None
            self._dragging = False
            return True
        return False

    def _on_mouse_enter(self, *_):
        if not self.config.settings.get("zoom_on_hover", True):
            return
        if not self.is_hovering:
            self.is_hovering = True
            z = self.config.settings.get("zoom_factor", 1.25)
            self.resize(int(self.original_size[0]*z), int(self.original_size[1]*z))

    def _on_mouse_leave(self, *_):
        if not self.config.settings.get("zoom_on_hover", True):
            return
        if self.is_hovering:
            self.is_hovering = False
            self.resize(*self.original_size)

    def _on_destroy(self, *_):
        if not self._use_ls:
            # Layer-shell mode saves position in destroy() and _on_ls_pos().
            try:
                x, y = self.get_position()
                name = self.wnck_window.get_name()
                cfg = self.config.settings.setdefault("thumbnail_positions", {})
                cfg[name] = [x, y]
                self.config.save()
            except Exception:
                pass
        if self.update_id:
            try:
                GLib.source_remove(self.update_id)
            except Exception:
                pass
            self.update_id = None

class EVEOPreview(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.thumbnails = {}
        self.client_rows = {}        # xid → Gtk.ListBoxRow in the management window
        self._pending_watches = {}   # xid → handler_id for name-changed watchers
        # Session-only sticky xid → slot map. When an EVE client window is
        # given a slot (via right-click bind, character preference, or
        # auto-fill), the assignment stays with that *window* until it
        # closes — so a character logout/login in the same client preserves
        # the hotkey binding. Persistent character→slot prefs live in
        # config.slot_assignments separately.
        self._session_xid_slots = {}
        self.screen = Wnck.Screen.get_default()
        self.screen.force_update()

        # Dock mode: one resizable container for every thumbnail, instead of
        # nine floating tiny windows. Created lazily so non-dock-mode users
        # don't pay the construction cost.
        self._dock = None
        if self.config.settings.get("dock_mode", False):
            self._dock = ThumbnailDock(self.config)

        # xdg-desktop-portal GlobalShortcuts is the Wayland-native path for
        # third-party processes to bind global hotkeys. The portal client is
        # instantiated here but the handshake (which shows a permission
        # dialog) is NOT triggered until the user clicks "Register" in the
        # Hotkeys settings tab. This avoids surprising the meatbag with a
        # dialog on every launch.
        self._portal = None
        if self.config.settings.get("kde_hotkeys_enabled", True):
            try:
                self._portal = _PortalGlobalShortcuts(
                    on_pressed=self._on_hotkey_pressed,
                    on_state_change=self._on_portal_state,
                )
            except Exception as e:
                print(f"[portal] disabled: {e}")
                self._portal = None

        # KDE persists portal shortcuts across runs but each new process must
        # rebind the session for them to actually fire. Auto-rebind once we
        # know the user has registered before — BindShortcuts is silent when
        # every ID already exists in kglobalshortcutsrc for this app_id.
        if (self._portal is not None
                and self.config.settings.get("kde_hotkeys_registered", False)):
            GLib.idle_add(self._auto_rebind_shortcuts)

        self.set_title("EVE-O Preview")
        self.set_default_size(500, 400)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Apply modern styling
        self._apply_styles()

        # Header bar
        headerbar = Gtk.HeaderBar()
        headerbar.set_show_close_button(True)
        headerbar.set_title("EVE-O Preview")
        headerbar.set_subtitle("Linux Edition")
        self.set_titlebar(headerbar)

        # Settings button in header
        settings_btn = Gtk.Button()
        settings_icon = Gtk.Image.new_from_icon_name("preferences-system", Gtk.IconSize.BUTTON)
        settings_btn.set_image(settings_icon)
        settings_btn.set_tooltip_text("Settings")
        settings_btn.connect("clicked", self._show_settings)
        headerbar.pack_end(settings_btn)

        # Main container
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(vbox)

        # Info bar
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        info_box.set_margin_start(12)
        info_box.set_margin_end(12)
        info_box.set_margin_top(10)
        info_box.set_margin_bottom(10)
        
        session = os.environ.get("XDG_SESSION_TYPE", "unknown")
        backend = os.environ.get("GDK_BACKEND", "unknown")
        
        session_label = Gtk.Label(label=f"Session: {session}")
        info_box.pack_start(session_label, False, False, 0)
        
        separator1 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        info_box.pack_start(separator1, False, False, 0)
        
        backend_label = Gtk.Label(label=f"Backend: {backend}")
        info_box.pack_start(backend_label, False, False, 0)
        
        vbox.pack_start(info_box, False, False, 0)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        vbox.pack_start(sep, False, False, 0)

        # Status bar
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_box.set_margin_start(12)
        status_box.set_margin_end(12)
        status_box.set_margin_top(8)
        status_box.set_margin_bottom(8)
        
        self.status_icon = Gtk.Image.new_from_icon_name("emblem-system", Gtk.IconSize.MENU)
        status_box.pack_start(self.status_icon, False, False, 0)
        
        self.status_label = Gtk.Label(label="Scanning for EVE clients...")
        self.status_label.set_halign(Gtk.Align.START)
        status_box.pack_start(self.status_label, True, True, 0)
        
        vbox.pack_start(status_box, False, False, 0)

        # Client list with frame
        frame = Gtk.Frame()
        frame.set_margin_start(12)
        frame.set_margin_end(12)
        frame.set_margin_bottom(12)
        frame.set_shadow_type(Gtk.ShadowType.IN)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(150)
        
        self.client_list = Gtk.ListBox()
        self.client_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scrolled.add(self.client_list)
        frame.add(scrolled)
        
        vbox.pack_start(frame, True, True, 0)

        self.screen.connect("window-opened", self._on_window_opened)
        self.screen.connect("window-closed", self._on_window_closed)
        self.screen.connect("active-window-changed", self._on_active_changed)

        # Periodic safety-net poll: KDE Plasma 6 sometimes doesn't fire
        # active-window-changed after alt-tab between XWayland windows.
        self._last_polled_active_xid = None
        GLib.timeout_add(1000, self._periodic_active_poll)

        self._scan_existing()
        GLib.timeout_add(2000, self._periodic_client_scan)

    def register_global_shortcuts(self):
        """User-initiated: open the portal permission dialog for slots
        1..max_hotkey_slots. Triggered by the Settings → Hotkeys button."""
        if self._portal is None:
            return False
        max_slots = int(self.config.settings.get("max_hotkey_slots", 9) or 9)
        desired = []
        for slot in range(1, max_slots + 1):
            desired.append((
                f"switch_slot_{slot}",
                f"EVE Online — Activate slot {slot}",
                f"Ctrl+Shift+{slot}",
            ))
        # Bonus shortcut: cycle through bound EVE clients in slot order.
        desired.append((
            "next_window",
            "EVE Online — Cycle to next bound client",
            "Ctrl+Shift+Space",
        ))
        self._portal.set_desired_shortcuts(desired)
        # If a session already exists, rebind (re-prompts the user); otherwise
        # do the full CreateSession + BindShortcuts handshake.
        if self._portal.state() == "active":
            self._portal.rebind()
        else:
            self._portal.stop()  # idempotent — ensures clean state
            self._portal.start()
        return True

    def _auto_rebind_shortcuts(self):
        """Silent rebind on app launch — no dialog because the IDs already
        exist in kglobalshortcutsrc. Reuses ``register_global_shortcuts`` so
        the desired list stays in sync with the user-facing path."""
        try:
            self.register_global_shortcuts()
        except Exception as e:
            print(f"[portal] auto-rebind failed: {e}")
        return False  # one-shot idle

    def _apply_styles(self):
        css_provider = Gtk.CssProvider()
        css = b"""
        .client-row {
            padding: 8px;
        }
        .client-name {
            font-weight: bold;
        }
        """
        css_provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _scan_existing(self):
        for w in self.screen.get_windows():
            self._check_and_add(w)
        self._update_status()

        # Apply active-client state immediately after startup discovery.
        # Without this, "Hide active client thumbnail" may not take effect
        # until the first focus/window switch signal is received.
        self.screen.force_update()
        active = self.screen.get_active_window()
        if active:
            active_xid = active.get_xid()
            self._apply_active_borders(active_xid)
            self._last_polled_active_xid = active_xid

        # KDE/Wayland startup timing can briefly report no or stale active
        # XWayland window. Reuse the existing short retry path as a safety net.
        self._poll_retries = [0]
        GLib.timeout_add(150, self._poll_active_border)

    def _check_and_add(self, window):
        if is_eve_window_steamaware(window):
            xid = window.get_xid()
            if xid not in self.thumbnails:
                self._add_thumb(window)
            return True
        return False

    def _place_thumb(self, thumb):
        screen = Gdk.Screen.get_default()
        if screen is not None:
            try:
                mon_idx = screen.get_primary_monitor()
            except Exception:
                mon_idx = 0
            geo = screen.get_monitor_geometry(mon_idx)
            sx, sy, sw, sh = geo.x, geo.y, geo.width, geo.height
        else:
            sx, sy, sw, sh = 0, 0, 1920, 1080

        tw = self.config.settings["thumbnail_width"]
        th = self.config.settings["thumbnail_height"]
        margin = 12
        cols = max(1, (sw - margin) // (tw + margin))
        idx = len(self.thumbnails) - 1
        x = sx + margin + (idx % cols) * (tw + margin)
        y = sy + margin + (idx // cols) * (th + margin)
        thumb.move(x, y)

    def _add_thumb(self, window):
        xid = window.get_xid()
        thumb = ThumbnailWindow(window, self.config, self._activate_window)
        self.thumbnails[xid] = thumb
        thumb.bind_live(xid, self.config.settings["thumbnail_width"], self.config.settings["thumbnail_height"])

        name = window.get_name()
        if self._dock is not None:
            # Dock mode — the ThumbnailWindow keeps capturing but is never
            # shown. A _ThumbnailItem inside the dock mirrors its pixbuf.
            self._dock.add_thumb(xid, thumb, self._activate_window)
        else:
            pos = self.config.settings.get("thumbnail_positions", {}).get(name)
            if pos:
                thumb.move(int(pos[0]), int(pos[1]))
            else:
                self._place_thumb(thumb)
            # show_all() after positioning so the layer-shell subprocess receives POS
            # before the first frame, preventing a visible jump from (0,0).
            thumb.show_all()

        # Create styled list row
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("client-row")
        
        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row_box.set_margin_start(8)
        row_box.set_margin_end(8)
        
        icon = Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.DND)
        row_box.pack_start(icon, False, False, 0)
        
        label = Gtk.Label(label=name)
        label.get_style_context().add_class("client-name")
        label.set_halign(Gtk.Align.START)
        label.set_ellipsize(3)  # Ellipsize at end
        row_box.pack_start(label, True, True, 0)
        
        # Wrap row_box in an EventBox so we can capture right-clicks for the
        # slot-binding popup menu. The EventBox lives BETWEEN row and row_box
        # so that ListBoxRow's selection logic stays intact for left-clicks.
        evbox = Gtk.EventBox()
        evbox.add(row_box)
        evbox.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        evbox.connect("button-press-event", self._on_client_row_button, window)
        row.add(evbox)
        self.client_list.add(row)
        row.show_all()
        self.client_rows[xid] = row

        def _refresh_row_label(*_args):
            raw = window.get_name() or "EVE"
            display = raw
            if " - " in raw:
                display = raw.split(" - ", 1)[1].split("[")[0].strip()
            # Decorate with the current slot binding if one exists.
            bindings = self._compute_slot_bindings()
            slot_num = None
            for slot_str, info in bindings.items():
                if info.get("character_name") == display:
                    slot_num = slot_str
                    break
            if slot_num:
                label.set_markup(
                    f"<tt>[{slot_num}]</tt>  {GLib.markup_escape_text(display)}"
                )
            else:
                label.set_text(display)
            # Title change can mean a different character logged in on the
            # same client window — re-emit slots.json with the new name.
            self._write_slots_state()
        window.connect("name-changed", _refresh_row_label)
        _refresh_row_label()

        # Stash the label refresher so right-click menu actions can re-trigger it.
        row._refresh_label = _refresh_row_label

        self._update_status()
        self._write_slots_state()
        # Refresh all row labels (since a newly-detected client may have
        # been auto-assigned a slot that affects how it displays).
        for r in self.client_rows.values():
            try:
                r._refresh_label()
            except Exception:
                pass

    def _remove_thumb(self, xid):
        if self._dock is not None:
            self._dock.remove_thumb(xid)

        t = self.thumbnails.pop(xid, None)
        if t:
            t.destroy()

        row = self.client_rows.pop(xid, None)
        if row:
            row.destroy()

        # Window is gone — drop its sticky slot binding so future windows
        # (or relaunches of EVE) get a fresh assignment.
        self._session_xid_slots.pop(xid, None)

        self._update_status()
        self._write_slots_state()

    def _on_window_opened(self, _screen, window):
        if not self._check_and_add(window):
            # Only watch windows that might be EVE (by PID) — not every
            # random window on the desktop.  This prevents accumulating
            # name-changed handlers on hundreds of unrelated windows.
            xid = window.get_xid()
            if xid in self._pending_watches:
                return  # already watching
            pid = 0
            try:
                pid = window.get_pid() or 0
            except Exception:
                pass
            if pid and _is_real_eve_client_process(pid):
                hid = window.connect("name-changed", self._on_pending_window_name_changed)
                self._pending_watches[xid] = hid

    def _on_pending_window_name_changed(self, window):
        if self._check_and_add(window):
            # Successfully added — disconnect the watcher so it stops
            # running is_eve_window_steamaware + proc reads on every title change.
            xid = window.get_xid()
            hid = self._pending_watches.pop(xid, None)
            if hid:
                try:
                    window.disconnect(hid)
                except Exception:
                    pass

    def _on_window_closed(self, _screen, window):
        xid = window.get_xid()
        self._pending_watches.pop(xid, None)
        self._remove_thumb(xid)

    def _periodic_client_scan(self):
        """Safety-net scan for missed Wnck open/close signals.

        KDE Plasma / XWayland / Wine can occasionally miss a window-opened or
        window-closed transition while EVE is changing from launcher/loading
        windows into the final character client window. This keeps the client
        list and thumbnail set in sync without requiring an app restart.
        """
        try:
            self.screen.force_update()
            windows = list(self.screen.get_windows())
            live_xids = {w.get_xid() for w in windows}

            for w in windows:
                self._check_and_add(w)

            for xid in list(self.thumbnails.keys()):
                if xid not in live_xids:
                    self._remove_thumb(xid)

            active = self.screen.get_active_window()
            if active:
                self._apply_active_borders(active.get_xid())
        except Exception as e:
            print(f"[scan] periodic client scan error: {e}")
        return True

    def _on_active_changed(self, _screen, _prev):
        active = self.screen.get_active_window()
        # active can be None when a Wayland-native surface (e.g. alt-tab
        # switcher, layer-shell overlay, app launcher) takes focus — the X11
        # _NET_ACTIVE_WINDOW is momentarily cleared. On KDE Plasma 6 the signal
        # may not fire again when the XWayland window actually receives focus, so
        # schedule a delayed re-check instead of returning early.
        if not active:
            self._poll_retries = [0]
            GLib.timeout_add(150, self._poll_active_border)
            return
        self._apply_active_borders(active.get_xid())

    def _poll_active_border(self):
        """Retry active-border update after a short delay (alt-tab recovery).
        Retries up to 6 times (≈900ms total) to handle KDE Plasma 6 where
        _NET_ACTIVE_WINDOW may settle slowly after the compositor switch.
        """
        self.screen.force_update()  # flush stale Wnck X11 cache
        active = self.screen.get_active_window()
        if active:
            self._apply_active_borders(active.get_xid())
            return False  # done
        self._poll_retries[0] += 1
        if self._poll_retries[0] < 6:
            return True  # retry (GLib.timeout_add repeats while True)
        return False  # give up

    def _periodic_active_poll(self):
        """Safety-net: re-sync borders in case signal was missed.
        Avoids calling force_update() when unnecessary — it's expensive because
        it processes ALL pending X events synchronously, which with two Wine
        clients can be a significant burst.
        """
        if not self.thumbnails:
            return True  # nothing to sync
        # Try without force_update first — the signal path handles most cases.
        active = self.screen.get_active_window()
        if not active:
            # KDE Plasma 6 edge case: _NET_ACTIVE_WINDOW not yet updated.
            # Only now pay the force_update() cost.
            self.screen.force_update()
            active = self.screen.get_active_window()
        if active:
            xid = active.get_xid()
            if xid != self._last_polled_active_xid:
                self._last_polled_active_xid = xid
                self._apply_active_borders(xid)
            else:
                # XID unchanged — just re-send active state without the raise
                # timer, in case a subprocess border drifted out of sync.
                for t_xid, t in self.thumbnails.items():
                    t.set_active_state(t_xid == xid)
        return True  # keep repeating

    def _apply_active_borders(self, active_xid):
        if self._dock is not None:
            self._dock.set_active(active_xid)
        for xid, t in self.thumbnails.items():
            is_active = (xid == active_xid)

            # Update border color
            t.set_active_state(is_active)

            # Hide/show based on setting
            if self.config.settings.get("hide_active_client", False):
                t.hide() if is_active else t.show()

            # Update opacity (layer-shell subprocess doesn't support GTK opacity)
            if not t._use_ls:
                try:
                    t.set_opacity(1.0 if is_active else self.config.settings.get("opacity", 0.95))
                except Exception:
                    pass

        # Defer re-raise for XWayland thumbnails only (layer-shell is always on top).
        if self.config.settings.get("always_on_top", True):
            GLib.timeout_add(100, self._raise_all_thumbnails)

    def _raise_all_thumbnails(self):
        for t in self.thumbnails.values():
            if t._use_ls:
                continue  # Layer-shell OVERLAY needs no raising
            try:
                t.set_keep_above(True)
                gdkwin = t.get_window()
                if gdkwin:
                    gdkwin.raise_()
            except Exception:
                pass
        return False   # don't repeat

    def _activate_window(self, window):
        try:
            if window.is_minimized():
                window.unminimize(Gtk.get_current_event_time())
            window.activate(Gtk.get_current_event_time())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Hotkey slot binding
    # ------------------------------------------------------------------
    # The running app maintains a JSON file at config_dir/slots.json mapping
    # slot numbers (as strings, "1"–"9") to current EVE clients. The
    # companion eve-switch script reads this file and activates the bound
    # window. KDE custom shortcuts (Meta+1, Meta+2, …) call eve-switch — so
    # the hotkey bindings themselves are static while their *targets* update
    # dynamically as clients open and close.
    def _character_name_for_xid(self, xid):
        thumb = self.thumbnails.get(xid)
        if not thumb:
            return None
        raw = thumb.wnck_window.get_name() or ""
        if " - " in raw:
            name = raw.split(" - ", 1)[1]
            if "[" in name:
                name = name.split("[")[0]
            return name.strip()
        return raw.strip() or None

    def _compute_slot_bindings(self):
        """Return {slot_str: {xid_hex, character_name, window_title}} for
        currently-tracked EVE clients.

        Priority order:
          1. **Sticky xid binding** — if this window has already been given
             a slot this session (via right-click, character preference, or
             auto-fill), keep it. This is what lets a character logout/
             login *in the same client* preserve the hotkey.
          2. **Character preference** — for windows without a sticky slot
             yet, look up the character's preferred slot in the saved
             ``slot_assignments`` config.
          3. **Auto-fill** — anything else lands in the lowest free slot.

        Side effects (mutate ``self._session_xid_slots`` and persist
        character→slot in config so next session remembers a manual bind):
          - Every assigned xid gets its slot recorded in the session map.
          - Every assigned character's slot is written to slot_assignments.
        """
        saved = dict(self.config.settings.get("slot_assignments", {}) or {})
        max_slots = int(self.config.settings.get("max_hotkey_slots", 9) or 9)

        char_xid_pairs = []
        for xid in self.thumbnails:
            name = self._character_name_for_xid(xid)
            if name:
                char_xid_pairs.append((name, xid))

        bindings = {}      # slot:int → (char_name, xid)
        used = set()

        # Phase 1: honor sticky xid bindings from this session.
        unstuck = []
        for name, xid in char_xid_pairs:
            stuck = self._session_xid_slots.get(xid)
            if isinstance(stuck, int) and 1 <= stuck <= max_slots and stuck not in used:
                used.add(stuck)
                bindings[stuck] = (name, xid)
                saved[name] = stuck     # remember for future sessions
            else:
                unstuck.append((name, xid))

        # Phase 2: apply persisted character preferences for un-stuck windows.
        leftover = []
        for name, xid in unstuck:
            pref = saved.get(name)
            try:
                pslot = int(pref) if pref else 0
            except (TypeError, ValueError):
                pslot = 0
            if 1 <= pslot <= max_slots and pslot not in used:
                used.add(pslot)
                bindings[pslot] = (name, xid)
                self._session_xid_slots[xid] = pslot
            else:
                leftover.append((name, xid))

        # Phase 3: auto-fill the rest into the lowest free slots.
        next_slot = 1
        for name, xid in leftover:
            while next_slot in used and next_slot <= max_slots:
                next_slot += 1
            if next_slot > max_slots:
                break
            used.add(next_slot)
            bindings[next_slot] = (name, xid)
            self._session_xid_slots[xid] = next_slot
            saved[name] = next_slot

        # Persist any new character→slot mappings discovered.
        if saved != (self.config.settings.get("slot_assignments", {}) or {}):
            self.config.settings["slot_assignments"] = saved
            try:
                self.config.save()
            except Exception:
                pass

        out = {}
        for slot, (char_name, xid) in bindings.items():
            wnck_w = self.thumbnails[xid].wnck_window
            out[str(slot)] = {
                "xid": f"0x{xid:08x}",
                "character_name": char_name,
                "window_title": wnck_w.get_name() or "",
            }
        return out

    def _write_slots_state(self):
        """Recompute current slot→client bindings, atomically write the
        state file, propagate ordering into the dock, and reconcile
        kglobalaccel registrations to match."""
        try:
            bindings = self._compute_slot_bindings()
            state = {
                "slots": bindings,
                "max_slots": int(self.config.settings.get("max_hotkey_slots", 9) or 9),
            }
            path = self.config.slots_file
            existing = None
            try:
                if path.exists():
                    existing = json.loads(path.read_text())
            except Exception:
                existing = None
            if existing != state:
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(state, indent=2))
                tmp.replace(path)
        except Exception as e:
            print(f"[slots] write error: {e}")
            bindings = {}

        # Push the new ordering to the dock so it re-sorts the FlowBox by
        # slot number, eliminating gaps/out-of-order tiles after a client
        # disconnects and reopens.
        if self._dock is not None:
            try:
                self._dock.update_slot_order(bindings)
            except Exception as e:
                print(f"[dock] reorder error: {e}")

        # Portal bindings are FIXED at startup (slots 1..max_hotkey_slots).
        # We do not re-bind when EVE clients open/close — slots.json provides
        # the dynamic slot→character mapping that _on_hotkey_pressed reads.
        # If the user has disabled hotkeys, tear down the session.
        if self._portal is not None and not self.config.settings.get(
            "kde_hotkeys_enabled", True
        ):
            try:
                self._portal.stop()
            except Exception as e:
                print(f"[portal] disable cleanup error: {e}")

    def _on_hotkey_pressed(self, shortcut_id):
        """Portal Activated callback. ``shortcut_id`` is either
        ``switch_slot_N`` for a direct slot binding or ``next_window`` for
        the cycle-through binding.

        Uses the same activation cascade the thumbnail click path uses
        (wmctrl → xdotool → Xlib → Wnck) because plain Wnck.activate from a
        D-Bus signal context has no current-event timestamp and is rejected
        by KDE focus-stealing prevention.
        """
        import subprocess
        try:
            bindings = self._compute_slot_bindings()

            # Resolve the target slot.
            if shortcut_id == "next_window":
                target_slot = self._next_slot_in_cycle(bindings)
                if target_slot is None:
                    print("[portal] next_window: no bound clients")
                    return False
                entry = bindings.get(str(target_slot))
            elif shortcut_id.startswith("switch_slot_"):
                try:
                    target_slot = int(shortcut_id.rsplit("_", 1)[-1])
                except ValueError:
                    return False
                entry = bindings.get(str(target_slot))
            else:
                return False

            if not entry:
                print(f"[portal] {shortcut_id}: no client bound")
                return False
            target_xid_hex = entry.get("xid", "")
            try:
                target_xid = int(target_xid_hex, 16)
            except (TypeError, ValueError):
                return False
            thumb = self.thumbnails.get(target_xid)
            if thumb is None:
                return False
            wnck_w = thumb.wnck_window

            # Stage 1: unminimize if needed (cheap, always safe).
            try:
                if wnck_w.is_minimized():
                    wnck_w.unminimize(Gtk.get_current_event_time())
            except Exception:
                pass

            # Stage 2: wmctrl by xid — most reliable on KDE/XWayland.
            xid_hex = f"0x{target_xid:08x}"
            ok = False
            try:
                r = subprocess.run(["wmctrl", "-ia", xid_hex],
                                   capture_output=True, timeout=2)
                ok = (r.returncode == 0)
            except Exception:
                ok = False

            # Stage 3: xdotool fallback.
            if not ok:
                try:
                    r = subprocess.run(["xdotool", "windowactivate", "--sync",
                                        str(target_xid)],
                                       capture_output=True, timeout=2)
                    ok = (r.returncode == 0)
                except Exception:
                    ok = False

            # Stage 4: raw Xlib _NET_ACTIVE_WINDOW + XSetInputFocus.
            if not ok:
                try:
                    _net_activate_window(target_xid,
                                         Gtk.get_current_event_time() or 0)
                    ok = True
                except Exception:
                    ok = False

            # Stage 5: Wnck activate — last resort.
            if not ok:
                try:
                    wnck_w.activate(Gtk.get_current_event_time() or 0)
                except Exception:
                    pass

            print(f"[portal] {shortcut_id} → slot {target_slot} "
                  f"({entry.get('character_name','?')}) "
                  f"activated via {'wmctrl' if ok else 'fallback'}")
        except Exception as e:
            print(f"[portal] press handler error: {e}")
        return False  # one-shot idle callback

    def _next_slot_in_cycle(self, bindings):
        """Pick the slot to switch to when Ctrl+Shift+Space is pressed.

        Determines the currently-active EVE client (by Wnck's active-window
        XID) and returns the next slot in ascending order, wrapping around.
        Returns None when no slots are bound.
        """
        if not bindings:
            return None
        try:
            active_xid = None
            aw = self.screen.get_active_window()
            if aw:
                active_xid = aw.get_xid()
        except Exception:
            active_xid = None

        slots_sorted = sorted(int(s) for s in bindings.keys())
        if not slots_sorted:
            return None

        active_slot = None
        for s in slots_sorted:
            try:
                if int(bindings[str(s)]["xid"], 16) == active_xid:
                    active_slot = s
                    break
            except (TypeError, ValueError, KeyError):
                continue

        if active_slot is None:
            return slots_sorted[0]
        idx = slots_sorted.index(active_slot)
        return slots_sorted[(idx + 1) % len(slots_sorted)]

    def _on_client_row_button(self, widget, event, wnck_window):
        """Right-click on a client row: pop up a menu to bind it to a slot."""
        if event.button != 3:  # 3 = right
            return False
        # Resolve the character name for this row.
        xid = wnck_window.get_xid()
        char_name = self._character_name_for_xid(xid)
        if not char_name:
            return False

        max_slots = int(self.config.settings.get("max_hotkey_slots", 9) or 9)
        current = (self.config.settings.get("slot_assignments", {}) or {}).get(char_name)

        menu = Gtk.Menu()
        header = Gtk.MenuItem(label=f"Bind \"{char_name}\" to:")
        header.set_sensitive(False)
        menu.append(header)
        menu.append(Gtk.SeparatorMenuItem())

        for slot in range(1, max_slots + 1):
            lbl = f"Slot {slot}  (Ctrl+Shift+{slot})"
            if current == slot:
                lbl = f"● {lbl}"
            item = Gtk.MenuItem(label=lbl)
            item.connect(
                "activate",
                lambda _w, s=slot, c=char_name: self._set_character_slot(c, s),
            )
            menu.append(item)

        menu.append(Gtk.SeparatorMenuItem())
        auto = Gtk.MenuItem(label="Auto (no preferred slot)")
        if not current:
            auto.set_label("● Auto (no preferred slot)")
        auto.connect("activate", lambda _w, c=char_name: self._set_character_slot(c, 0))
        menu.append(auto)

        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def _set_character_slot(self, char_name, slot):
        """Bind a character to a specific slot (0 = unset). Clears any other
        character/window that was claiming that slot, so right-click
        reassignments produce intuitive single-active-per-slot results.

        Also updates the session xid map so the binding sticks to the
        character's *current window* — meaning a character swap in that
        same client will inherit this slot.
        """
        assignments = dict(self.config.settings.get("slot_assignments", {}) or {})

        # Find the xid currently displaying char_name (if any).
        target_xid = None
        for xid in self.thumbnails:
            if self._character_name_for_xid(xid) == char_name:
                target_xid = xid
                break

        if slot > 0:
            # Evict any other char/xid currently claiming this slot.
            for other, other_slot in list(assignments.items()):
                try:
                    if int(other_slot) == int(slot) and other != char_name:
                        assignments.pop(other, None)
                except (TypeError, ValueError):
                    pass
            for ev_xid, ev_slot in list(self._session_xid_slots.items()):
                if ev_slot == int(slot) and ev_xid != target_xid:
                    self._session_xid_slots.pop(ev_xid, None)

            assignments[char_name] = int(slot)
            if target_xid is not None:
                self._session_xid_slots[target_xid] = int(slot)
        else:
            assignments.pop(char_name, None)
            if target_xid is not None:
                self._session_xid_slots.pop(target_xid, None)

        self.config.settings["slot_assignments"] = assignments
        self.config.save()
        self._write_slots_state()
        for r in self.client_rows.values():
            try:
                r._refresh_label()
            except Exception:
                pass

    def _on_portal_state(self, state):
        """Receive state transitions from the portal client. On the first
        successful "active" transition, persist the registered flag so future
        launches auto-rebind silently."""
        print(f"[portal] state → {state}")
        if state == "active" and not self.config.settings.get(
                "kde_hotkeys_registered", False):
            self.config.settings["kde_hotkeys_registered"] = True
            try:
                self.config.save()
            except Exception as e:
                print(f"[portal] config save after registration failed: {e}")

    def shutdown_hotkeys(self):
        """Tear down portal session and signal subscription. Called on exit."""
        if self._portal is not None:
            try:
                self._portal.stop()
            except Exception as e:
                print(f"[portal] shutdown error: {e}")

    def _show_settings(self, _btn):
        # Diagnostic trace — survives even when stdout is detached
        # (launcher launches send stdout to the journal at best).
        try:
            import traceback as _tb
            with open("/tmp/eve-o-preview-settings.log", "a") as _lg:
                _lg.write(f"[{time.time():.3f}] _show_settings click; "
                          f"win mapped={self.get_mapped()} "
                          f"visible={self.get_visible()} "
                          f"realized={self.get_realized()}\n")
        except Exception:
            pass
        try:
            dialog = SettingsDialog(self, self.config)
        except Exception:
            with open("/tmp/eve-o-preview-settings.log", "a") as _lg:
                _lg.write(f"[{time.time():.3f}] SettingsDialog __init__ RAISED:\n")
                _tb.print_exc(file=_lg)
            return
        # show_all() already runs inside SettingsDialog.__init__; present()
        # also raises the window to the top of its stacking layer. Avoid
        # present_with_time(CURRENT_TIME=0) — Wayland focus-stealing
        # prevention sometimes treats the missing timestamp as stale.
        dialog.present()
        with open("/tmp/eve-o-preview-settings.log", "a") as _lg:
            _lg.write(f"[{time.time():.3f}] dialog created and presented; "
                      f"about to call run()\n")
        if dialog.run() == Gtk.ResponseType.OK:
            dialog.save_settings()
            for t in self.thumbnails.values():
                t.original_size = (self.config.settings["thumbnail_width"],
                                   self.config.settings["thumbnail_height"])
                t.resize(*t.original_size)
                t._target_w, t._target_h = t.original_size
                if not t._use_ls:
                    try:
                        t.set_opacity(self.config.settings.get("opacity", 0.95))
                    except Exception:
                        pass
                    # Update overlay visibility (only applies to GTK-rendered thumbnails)
                    if hasattr(t, 'label'):
                        if self.config.settings.get("show_overlay", True):
                            t.label.show()
                        else:
                            t.label.hide()
                    # Update border colors
                    t._update_border_style()
                # Restart capture timer with new FPS (applies to both modes)
                if t.live_window:
                    t._start_live_timer()
        dialog.destroy()
        try:
            with open("/tmp/eve-o-preview-settings.log", "a") as _lg:
                _lg.write(f"[{time.time():.3f}] dialog destroyed; restoring focus\n")
        except Exception:
            pass
        # Restore focus + raise the main window. Without this, KDE/Wayland
        # sometimes leaves the management window without keyboard focus after
        # a modal-run() completes, which makes the next click on the Settings
        # button get swallowed by the WM until the user re-focuses manually.
        try:
            self.present()
        except Exception:
            pass

    def _update_status(self):
        count = len(self.thumbnails)
        if count == 0:
            self.status_label.set_text("No EVE clients detected")
            self.status_icon.set_from_icon_name("dialog-warning", Gtk.IconSize.MENU)
        else:
            self.status_label.set_text(f"Monitoring {count} EVE client{'s' if count != 1 else ''}")
            self.status_icon.set_from_icon_name("emblem-default", Gtk.IconSize.MENU)

class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        super().__init__(
            title="Settings",
            parent=parent,
            flags=Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        self.config = config
        self._parent_app = parent   # EVEOPreview — used by Hotkeys tab
        self._slot_widgets = {}     # character_name → Gtk.SpinButton
        self.set_default_size(520, 560)
        self.set_resizable(False)
        # The dock and main window both keep_above=True. Match that so the
        # dialog doesn't get buried under them. Combining keep_above with the
        # MODAL flag confuses KWin's input grab on Wayland (the next Settings
        # button click stops registering), so rely on Gtk.Dialog.run()'s own
        # nested loop for modality and skip the WM-level modal flag.
        self.set_keep_above(True)

        # Header bar for dialog
        headerbar = Gtk.HeaderBar()
        headerbar.set_show_close_button(False)
        headerbar.set_title("Settings")
        self.set_titlebar(headerbar)

        # Buttons in header
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda x: self.response(Gtk.ResponseType.CANCEL))
        headerbar.pack_start(cancel_btn)

        apply_btn = Gtk.Button(label="Apply")
        apply_btn.get_style_context().add_class("suggested-action")
        apply_btn.connect("clicked", lambda x: self.response(Gtk.ResponseType.OK))
        headerbar.pack_end(apply_btn)

        box = self.get_content_area()
        box.set_spacing(0)

        # Apply styles
        self._apply_styles()

        # Create notebook for categories
        notebook = Gtk.Notebook()
        notebook.set_margin_start(0)
        notebook.set_margin_end(0)
        notebook.set_margin_top(0)
        notebook.set_margin_bottom(0)
        box.add(notebook)

        # Display settings page
        display_page = self._create_display_page()
        notebook.append_page(display_page, Gtk.Label(label="Display"))

        # Behavior settings page
        behavior_page = self._create_behavior_page()
        notebook.append_page(behavior_page, Gtk.Label(label="Behavior"))

        # Hotkeys / slot assignment page
        hotkeys_page = self._create_hotkeys_page()
        notebook.append_page(hotkeys_page, Gtk.Label(label="Hotkeys"))

        self.show_all()

    def _apply_styles(self):
        css_provider = Gtk.CssProvider()
        css = b"""
        .section-title {
            font-weight: bold;
            margin-bottom: 8px;
        }
        """
        css_provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _create_display_page(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.set_margin_start(15)
        vbox.set_margin_end(15)
        vbox.set_margin_top(15)
        vbox.set_margin_bottom(15)

        # Dimensions section
        dim_label = Gtk.Label(label="Thumbnail Dimensions")
        dim_label.set_halign(Gtk.Align.START)
        dim_label.get_style_context().add_class("section-title")
        vbox.pack_start(dim_label, False, False, 0)

        dim_grid = Gtk.Grid()
        dim_grid.set_column_spacing(10)
        dim_grid.set_row_spacing(8)
        dim_grid.set_margin_start(8)
        dim_grid.set_margin_bottom(15)

        # Width
        width_label = Gtk.Label(label="Width:")
        width_label.set_halign(Gtk.Align.END)
        dim_grid.attach(width_label, 0, 0, 1, 1)
        
        self.w_spin = Gtk.SpinButton()
        self.w_spin.set_range(100, 800)
        self.w_spin.set_increments(10, 50)
        self.w_spin.set_value(self.config.settings["thumbnail_width"])
        self.w_spin.set_hexpand(True)
        dim_grid.attach(self.w_spin, 1, 0, 1, 1)
        
        width_px = Gtk.Label(label="px")
        dim_grid.attach(width_px, 2, 0, 1, 1)

        # Height
        height_label = Gtk.Label(label="Height:")
        height_label.set_halign(Gtk.Align.END)
        dim_grid.attach(height_label, 0, 1, 1, 1)
        
        self.h_spin = Gtk.SpinButton()
        self.h_spin.set_range(80, 600)
        self.h_spin.set_increments(10, 50)
        self.h_spin.set_value(self.config.settings["thumbnail_height"])
        self.h_spin.set_hexpand(True)
        dim_grid.attach(self.h_spin, 1, 1, 1, 1)
        
        height_px = Gtk.Label(label="px")
        dim_grid.attach(height_px, 2, 1, 1, 1)

        vbox.pack_start(dim_grid, False, False, 0)

        # Appearance section
        appear_label = Gtk.Label(label="Appearance")
        appear_label.set_halign(Gtk.Align.START)
        appear_label.get_style_context().add_class("section-title")
        vbox.pack_start(appear_label, False, False, 0)

        appear_grid = Gtk.Grid()
        appear_grid.set_column_spacing(10)
        appear_grid.set_row_spacing(8)
        appear_grid.set_margin_start(8)

        # Opacity
        opacity_label = Gtk.Label(label="Opacity:")
        opacity_label.set_halign(Gtk.Align.END)
        appear_grid.attach(opacity_label, 0, 0, 1, 1)
        
        opacity_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.opacity = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.2, 1.0, 0.05)
        self.opacity.set_value(self.config.settings["opacity"])
        self.opacity.set_hexpand(True)
        self.opacity.set_value_pos(Gtk.PositionType.RIGHT)
        self.opacity.set_digits(2)
        opacity_box.pack_start(self.opacity, True, True, 0)
        appear_grid.attach(opacity_box, 1, 0, 2, 1)

        vbox.pack_start(appear_grid, False, False, 0)

        # Active border color
        border_label = Gtk.Label(label="Active Border Color")
        border_label.set_halign(Gtk.Align.START)
        border_label.get_style_context().add_class("section-title")
        border_label.set_margin_top(10)
        vbox.pack_start(border_label, False, False, 0)

        border_grid = Gtk.Grid()
        border_grid.set_column_spacing(10)
        border_grid.set_row_spacing(8)
        border_grid.set_margin_start(8)

        color_label = Gtk.Label(label="Color (Hex):")
        color_label.set_halign(Gtk.Align.END)
        border_grid.attach(color_label, 0, 0, 1, 1)

        # Color entry box
        color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        self.color_entry = Gtk.Entry()
        self.color_entry.set_text(self.config.settings.get("active_border_color", "#00FF00"))
        self.color_entry.set_max_length(7)
        self.color_entry.set_width_chars(10)
        self.color_entry.set_placeholder_text("#00FF00")
        color_box.pack_start(self.color_entry, False, False, 0)
        
        # Color button for visual picker
        current_color = self.config.settings.get("active_border_color", "#00FF00")
        rgba = Gdk.RGBA()
        rgba.parse(current_color)
        
        self.color_button = Gtk.ColorButton()
        self.color_button.set_rgba(rgba)
        self.color_button.set_title("Choose Border Color")
        self.color_button.connect("color-set", self._on_color_picked)
        color_box.pack_start(self.color_button, False, False, 0)
        
        # Preview box
        self.color_preview = Gtk.DrawingArea()
        self.color_preview.set_size_request(30, 30)
        self.color_preview.connect("draw", self._draw_color_preview)
        color_box.pack_start(self.color_preview, False, False, 0)
        
        border_grid.attach(color_box, 1, 0, 2, 1)
        
        # Preset colors
        preset_label = Gtk.Label(label="Presets:")
        preset_label.set_halign(Gtk.Align.END)
        border_grid.attach(preset_label, 0, 1, 1, 1)
        
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        presets = [
            ("#00FF00", "Neon Green"),
            ("#00FFFF", "Cyan"),
            ("#FF00FF", "Magenta"),
            ("#FFFF00", "Yellow"),
            ("#FF0000", "Red"),
            ("#0080FF", "Blue")
        ]
        
        for color, tooltip in presets:
            btn = Gtk.Button()
            btn.set_size_request(25, 25)
            btn.set_tooltip_text(tooltip)
            btn.connect("clicked", self._on_preset_clicked, color)
            
            # Style the button with the color
            css = Gtk.CssProvider()
            css.load_from_data(f"button {{ background: {color}; min-width: 25px; min-height: 25px; border-radius: 3px; }}".encode())
            btn.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            
            preset_box.pack_start(btn, False, False, 0)
        
        border_grid.attach(preset_box, 1, 1, 2, 1)
        
        vbox.pack_start(border_grid, False, False, 0)

        return vbox

    def _on_color_picked(self, color_button):
        """When color is picked from ColorButton, update entry"""
        rgba = color_button.get_rgba()
        hex_color = "#{:02x}{:02x}{:02x}".format(
            int(rgba.red * 255),
            int(rgba.green * 255),
            int(rgba.blue * 255)
        ).upper()
        self.color_entry.set_text(hex_color)
        self.color_preview.queue_draw()

    def _on_preset_clicked(self, button, color):
        """When preset color is clicked"""
        self.color_entry.set_text(color)
        rgba = Gdk.RGBA()
        rgba.parse(color)
        self.color_button.set_rgba(rgba)
        self.color_preview.queue_draw()

    def _draw_color_preview(self, widget, cr):
        """Draw the color preview box"""
        try:
            color_text = self.color_entry.get_text()
            if not color_text.startswith("#") or len(color_text) != 7:
                color_text = "#00FF00"
            
            rgba = Gdk.RGBA()
            if rgba.parse(color_text):
                cr.set_source_rgb(rgba.red, rgba.green, rgba.blue)
                cr.rectangle(0, 0, widget.get_allocated_width(), widget.get_allocated_height())
                cr.fill()
                
                # Draw border
                cr.set_source_rgb(0, 0, 0)
                cr.set_line_width(1)
                cr.rectangle(0, 0, widget.get_allocated_width(), widget.get_allocated_height())
                cr.stroke()
        except Exception:
            pass
        return False

    def _create_behavior_page(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.set_margin_start(15)
        vbox.set_margin_end(15)
        vbox.set_margin_top(15)
        vbox.set_margin_bottom(15)

        # Window behavior section
        behavior_label = Gtk.Label(label="Window Behavior")
        behavior_label.set_halign(Gtk.Align.START)
        behavior_label.get_style_context().add_class("section-title")
        vbox.pack_start(behavior_label, False, False, 0)

        behavior_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        behavior_box.set_margin_start(8)
        behavior_box.set_margin_bottom(15)

        self.always_on_top = Gtk.CheckButton(label="Keep thumbnails always on top")
        self.always_on_top.set_active(self.config.settings["always_on_top"])
        behavior_box.pack_start(self.always_on_top, False, False, 0)

        self.hide_active = Gtk.CheckButton(label="Hide active client thumbnail")
        self.hide_active.set_active(self.config.settings["hide_active_client"])
        behavior_box.pack_start(self.hide_active, False, False, 0)

        self.show_overlay = Gtk.CheckButton(label="Show character name overlay")
        self.show_overlay.set_active(self.config.settings["show_overlay"])
        behavior_box.pack_start(self.show_overlay, False, False, 0)

        self.dock_mode = Gtk.CheckButton(
            label="Dock mode — all thumbnails in one resizable window"
        )
        self.dock_mode.set_active(bool(self.config.settings.get("dock_mode", False)))
        self.dock_mode.set_tooltip_text(
            "When on, all thumbnails are grouped into a single container "
            "window that can be moved and resized. Column count adapts to "
            "width. Takes effect after restart."
        )
        behavior_box.pack_start(self.dock_mode, False, False, 0)

        vbox.pack_start(behavior_box, False, False, 0)

        # Interaction section
        interact_label = Gtk.Label(label="Interaction")
        interact_label.set_halign(Gtk.Align.START)
        interact_label.get_style_context().add_class("section-title")
        vbox.pack_start(interact_label, False, False, 0)

        interact_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        interact_box.set_margin_start(8)
        interact_box.set_margin_bottom(15)

        self.zoom_hover = Gtk.CheckButton(label="Zoom thumbnail on mouse hover")
        self.zoom_hover.set_active(self.config.settings["zoom_on_hover"])
        interact_box.pack_start(self.zoom_hover, False, False, 0)

        # Zoom factor
        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        zoom_box.set_margin_start(20)
        zoom_label = Gtk.Label(label="Zoom factor:")
        zoom_box.pack_start(zoom_label, False, False, 0)
        
        self.zoom_factor = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1.1, 2.0, 0.05)
        self.zoom_factor.set_value(self.config.settings.get("zoom_factor", 1.25))
        self.zoom_factor.set_hexpand(True)
        self.zoom_factor.set_value_pos(Gtk.PositionType.RIGHT)
        self.zoom_factor.set_digits(2)
        zoom_box.pack_start(self.zoom_factor, True, True, 0)
        
        interact_box.pack_start(zoom_box, False, False, 0)

        vbox.pack_start(interact_box, False, False, 0)

        # Performance section
        perf_label = Gtk.Label(label="Performance")
        perf_label.set_halign(Gtk.Align.START)
        perf_label.get_style_context().add_class("section-title")
        vbox.pack_start(perf_label, False, False, 0)

        perf_grid = Gtk.Grid()
        perf_grid.set_column_spacing(10)
        perf_grid.set_row_spacing(8)
        perf_grid.set_margin_start(8)

        refresh_label = Gtk.Label(label="Refresh rate:")
        refresh_label.set_halign(Gtk.Align.END)
        refresh_label.set_tooltip_text("Higher FPS = smoother but more CPU usage")
        perf_grid.attach(refresh_label, 0, 0, 1, 1)

        # Create radio buttons for FPS options
        fps_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
        
        self.fps_10 = Gtk.RadioButton.new_with_label_from_widget(None, "10 FPS")
        fps_box.pack_start(self.fps_10, False, False, 0)
        
        self.fps_15 = Gtk.RadioButton.new_with_label_from_widget(self.fps_10, "15 FPS")
        fps_box.pack_start(self.fps_15, False, False, 0)
        
        self.fps_25 = Gtk.RadioButton.new_with_label_from_widget(self.fps_10, "25 FPS")
        fps_box.pack_start(self.fps_25, False, False, 0)

        self.fps_30 = Gtk.RadioButton.new_with_label_from_widget(self.fps_10, "30 FPS")
        self.fps_30.set_tooltip_text("30 FPS — higher CPU usage, best with 1-2 clients")
        fps_box.pack_start(self.fps_30, False, False, 0)

        # Set current FPS selection
        current_fps = self.config.settings.get("refresh_fps", 10)
        if current_fps == 10:
            self.fps_10.set_active(True)
        elif current_fps == 15:
            self.fps_15.set_active(True)
        elif current_fps == 25:
            self.fps_25.set_active(True)
        elif current_fps == 30:
            self.fps_30.set_active(True)
        else:
            self.fps_10.set_active(True)
        
        perf_grid.attach(fps_box, 1, 0, 2, 1)

        vbox.pack_start(perf_grid, False, False, 0)

        # Info section at bottom
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_box.set_margin_top(20)
        
        info_label = Gtk.Label(label="Tip: Left-click to focus • Left-drag to move\nRight-drag to reposition • Ctrl+Click to minimize")
        info_label.set_line_wrap(True)
        info_label.set_justify(Gtk.Justification.CENTER)
        info_label.set_halign(Gtk.Align.CENTER)
        info_box.pack_start(info_label, False, False, 0)
        
        vbox.pack_end(info_box, False, False, 0)

        return vbox

    def _create_hotkeys_page(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.set_margin_start(15)
        vbox.set_margin_end(15)
        vbox.set_margin_top(15)
        vbox.set_margin_bottom(15)

        intro = Gtk.Label()
        intro.set_markup(
            "Assign each character to a hotkey slot. KDE custom shortcuts call "
            "<tt>eve-switch &lt;N&gt;</tt>, which activates the currently-bound "
            "window for that slot. <b>0</b> = auto (lowest free slot)."
        )
        intro.set_line_wrap(True)
        intro.set_xalign(0)
        intro.set_margin_bottom(12)
        vbox.pack_start(intro, False, False, 0)

        section = Gtk.Label(label="Detected Characters")
        section.set_halign(Gtk.Align.START)
        section.get_style_context().add_class("section-title")
        vbox.pack_start(section, False, False, 0)

        # Gather every character we know about: currently-tracked clients
        # union with already-saved preferred-slot characters (so the meatbag
        # can pre-assign offline alts).
        live_chars = {}
        if self._parent_app is not None:
            for xid in list(self._parent_app.thumbnails.keys()):
                name = self._parent_app._character_name_for_xid(xid)
                if name:
                    live_chars[name] = True
        saved = self.config.settings.get("slot_assignments", {}) or {}
        all_chars = sorted(set(list(live_chars.keys()) + list(saved.keys())))

        if not all_chars:
            empty = Gtk.Label(label="(No EVE characters detected yet — log in and reopen settings.)")
            empty.set_xalign(0)
            empty.set_margin_start(8)
            empty.set_margin_top(4)
            empty.set_margin_bottom(12)
            vbox.pack_start(empty, False, False, 0)
        else:
            grid = Gtk.Grid()
            grid.set_column_spacing(12)
            grid.set_row_spacing(6)
            grid.set_margin_start(8)
            grid.set_margin_bottom(12)

            hdr_char = Gtk.Label()
            hdr_char.set_markup("<b>Character</b>")
            hdr_char.set_xalign(0)
            hdr_slot = Gtk.Label()
            hdr_slot.set_markup("<b>Slot</b>")
            hdr_slot.set_xalign(0)
            hdr_live = Gtk.Label()
            hdr_live.set_markup("<b>Status</b>")
            hdr_live.set_xalign(0)
            grid.attach(hdr_char, 0, 0, 1, 1)
            grid.attach(hdr_slot, 1, 0, 1, 1)
            grid.attach(hdr_live, 2, 0, 1, 1)

            max_slots = int(self.config.settings.get("max_hotkey_slots", 9) or 9)
            for row, char_name in enumerate(all_chars, start=1):
                name_lbl = Gtk.Label(label=char_name)
                name_lbl.set_xalign(0)
                grid.attach(name_lbl, 0, row, 1, 1)

                spin = Gtk.SpinButton()
                spin.set_range(0, max_slots)
                spin.set_increments(1, 1)
                try:
                    spin.set_value(int(saved.get(char_name, 0) or 0))
                except (TypeError, ValueError):
                    spin.set_value(0)
                grid.attach(spin, 1, row, 1, 1)
                self._slot_widgets[char_name] = spin

                status = Gtk.Label(label="● online" if char_name in live_chars else "○ offline")
                status.set_xalign(0)
                grid.attach(status, 2, row, 1, 1)

            vbox.pack_start(grid, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(8)
        sep.set_margin_bottom(8)
        vbox.pack_start(sep, False, False, 0)

        # xdg-desktop-portal GlobalShortcuts controls
        kde_label = Gtk.Label(label="Global Shortcuts (Wayland portal)")
        kde_label.set_halign(Gtk.Align.START)
        kde_label.get_style_context().add_class("section-title")
        vbox.pack_start(kde_label, False, False, 0)

        self.kde_enable_chk = Gtk.CheckButton(
            label="Enable global hotkeys"
        )
        self.kde_enable_chk.set_active(
            bool(self.config.settings.get("kde_hotkeys_enabled", True))
        )
        self.kde_enable_chk.set_margin_start(8)
        vbox.pack_start(self.kde_enable_chk, False, False, 0)

        # Max-slots spinner row
        slots_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        slots_row.set_margin_start(8)
        slots_row.set_margin_top(4)
        slots_lbl = Gtk.Label(label="Number of slots:")
        slots_lbl.set_xalign(0)
        slots_row.pack_start(slots_lbl, False, False, 0)
        self.max_slots_spin = Gtk.SpinButton()
        self.max_slots_spin.set_range(1, 9)
        self.max_slots_spin.set_increments(1, 1)
        self.max_slots_spin.set_value(
            int(self.config.settings.get("max_hotkey_slots", 9) or 9)
        )
        slots_row.pack_start(self.max_slots_spin, False, False, 0)
        slots_unit = Gtk.Label(label="(Ctrl+Shift+1 through Ctrl+Shift+N)")
        slots_unit.set_xalign(0)
        slots_row.pack_start(slots_unit, True, True, 0)
        vbox.pack_start(slots_row, False, False, 0)

        kde_hint = Gtk.Label()
        kde_hint.set_markup(
            "<small>Click <i>Register Shortcuts</i> to open the permission "
            "dialog. After approval, Ctrl+Shift+1…N activate whichever EVE "
            "client is currently bound to each slot. The slot→character "
            "mapping updates live as clients open and close.</small>"
        )
        kde_hint.set_line_wrap(True)
        kde_hint.set_xalign(0)
        kde_hint.set_margin_start(8)
        kde_hint.set_margin_top(4)
        kde_hint.set_margin_bottom(6)
        vbox.pack_start(kde_hint, False, False, 0)

        # Register button + status
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_margin_start(8)
        self._register_btn = Gtk.Button(label="Register Shortcuts")
        self._register_btn.connect("clicked", self._on_register_clicked)
        btn_row.pack_start(self._register_btn, False, False, 0)

        self._unregister_btn = Gtk.Button(label="Unregister")
        self._unregister_btn.connect("clicked", self._on_unregister_clicked)
        btn_row.pack_start(self._unregister_btn, False, False, 0)
        vbox.pack_start(btn_row, False, False, 0)

        self._kde_status_lbl = Gtk.Label()
        self._kde_status_lbl.set_xalign(0)
        self._kde_status_lbl.set_margin_start(8)
        self._kde_status_lbl.set_margin_top(6)
        self._refresh_kde_status_label()
        vbox.pack_start(self._kde_status_lbl, False, False, 0)

        # Show path to slots.json (helps debugging external integrations)
        try:
            slots_path = str(self.config.slots_file)
        except Exception:
            slots_path = "~/.config/eve-o-preview-linux/slots.json"
        path_lbl = Gtk.Label()
        path_lbl.set_markup(f"<small>State file: <tt>{slots_path}</tt></small>")
        path_lbl.set_xalign(0)
        path_lbl.set_margin_top(12)
        vbox.pack_end(path_lbl, False, False, 0)

        return vbox

    def _on_register_clicked(self, _btn):
        if self._parent_app is None:
            return
        # Persist the spinner value first so register_global_shortcuts() reads it.
        try:
            self.config.settings["max_hotkey_slots"] = int(
                self.max_slots_spin.get_value()
            )
            self.config.save()
        except Exception:
            pass
        ok = self._parent_app.register_global_shortcuts()
        # Refresh status after a brief delay so the portal handshake has time to
        # resolve before we read state().
        GLib.timeout_add(500, lambda: (self._refresh_kde_status_label(), False)[1])
        if not ok:
            self._kde_status_lbl.set_markup(
                "<small><span foreground='#cc0000'>Portal not available.</span></small>"
            )

    def _on_unregister_clicked(self, _btn):
        if self._parent_app is None or self._parent_app._portal is None:
            return
        portal = self._parent_app._portal
        try:
            portal.stop()
        except Exception as e:
            print(f"[portal] unregister error: {e}")
        # Closing the session alone doesn't remove the bindings KDE saved in
        # kglobalshortcutsrc — Register would then silently reuse them and
        # never re-prompt. Purge the kglobalaccel component so the next
        # Register click triggers a fresh OS dialog.
        try:
            portal.purge_kde_bindings()
        except Exception as e:
            print(f"[portal] kglobalaccel purge error: {e}")
        # Clear the auto-rebind flag so the next launch doesn't silently
        # re-establish the session the user just torn down.
        self.config.settings["kde_hotkeys_registered"] = False
        try:
            self.config.save()
        except Exception as e:
            print(f"[portal] config save after unregister failed: {e}")
        self._refresh_kde_status_label()

    def _refresh_kde_status_label(self):
        if self._parent_app is None or self._parent_app._portal is None:
            self._kde_status_lbl.set_markup(
                "<small><span foreground='#cc0000'>xdg-desktop-portal "
                "GlobalShortcuts not available — global hotkeys disabled.</span></small>"
            )
            return
        state = self._parent_app._portal.state()
        bound_ids = self._parent_app._portal.bound_ids()
        if state == "active" and bound_ids:
            bindings = self._parent_app._compute_slot_bindings()
            entries = []
            for sid in sorted(bound_ids, key=lambda x: int(x.rsplit("_", 1)[-1])):
                try:
                    slot = int(sid.rsplit("_", 1)[-1])
                except ValueError:
                    continue
                ch = bindings.get(str(slot), {}).get("character_name", "?")
                entries.append(f"Ctrl+Shift+{slot} → {ch}")
            self._kde_status_lbl.set_markup(
                "<small><span foreground='#008800'>● Active: "
                + GLib.markup_escape_text(" · ".join(entries))
                + "</span></small>"
            )
        elif state.startswith("error"):
            self._kde_status_lbl.set_markup(
                f"<small><span foreground='#cc0000'>Portal error: "
                f"{GLib.markup_escape_text(state)}</span></small>"
            )
        else:
            self._kde_status_lbl.set_markup(
                f"<small>Portal state: {GLib.markup_escape_text(state)} — "
                "first-time setup may show a permission dialog.</small>"
            )

    def save_settings(self):
        self.config.settings["thumbnail_width"] = int(self.w_spin.get_value())
        self.config.settings["thumbnail_height"] = int(self.h_spin.get_value())
        self.config.settings["opacity"] = float(self.opacity.get_value())
        self.config.settings["always_on_top"] = self.always_on_top.get_active()
        self.config.settings["hide_active_client"] = self.hide_active.get_active()
        self.config.settings["zoom_on_hover"] = self.zoom_hover.get_active()
        self.config.settings["zoom_factor"] = float(self.zoom_factor.get_value())
        self.config.settings["show_overlay"] = self.show_overlay.get_active()
        
        # Save border color
        color_text = self.color_entry.get_text()
        if color_text.startswith("#") and len(color_text) == 7:
            self.config.settings["active_border_color"] = color_text.upper()
        
        # Save FPS selection
        if self.fps_10.get_active():
            self.config.settings["refresh_fps"] = 10
        elif self.fps_15.get_active():
            self.config.settings["refresh_fps"] = 15
        elif self.fps_25.get_active():
            self.config.settings["refresh_fps"] = 25
        elif self.fps_30.get_active():
            self.config.settings["refresh_fps"] = 30

        # Save slot assignments from the Hotkeys tab. A slot of 0 means
        # "auto-pick lowest free slot" — store as 0 so absence vs unassigned
        # is unambiguous when displayed next time.
        if self._slot_widgets:
            slot_assignments = dict(self.config.settings.get("slot_assignments", {}) or {})
            for char_name, spin in self._slot_widgets.items():
                try:
                    slot = int(spin.get_value())
                except (TypeError, ValueError):
                    slot = 0
                if slot <= 0:
                    slot_assignments.pop(char_name, None)
                else:
                    slot_assignments[char_name] = slot
            self.config.settings["slot_assignments"] = slot_assignments

        if hasattr(self, "dock_mode"):
            self.config.settings["dock_mode"] = bool(self.dock_mode.get_active())

        # Save Hotkeys tab settings
        if hasattr(self, "kde_enable_chk"):
            self.config.settings["kde_hotkeys_enabled"] = bool(
                self.kde_enable_chk.get_active()
            )
        if hasattr(self, "max_slots_spin"):
            self.config.settings["max_hotkey_slots"] = int(
                self.max_slots_spin.get_value()
            )

        self.config.save()

        # Re-emit slots.json AND reconcile kglobalaccel registrations.
        # _write_slots_state() handles both: it computes the current
        # bindings and the registration set in one pass.
        if self._parent_app is not None:
            try:
                self._parent_app._write_slots_state()
            except Exception as e:
                print(f"[slots] post-save rewrite error: {e}")

def main():
    screen = Wnck.Screen.get_default()
    if screen is None:
        if _WAYLAND_SESSION:
            print("[eve-o-preview] ERROR: Wnck could not connect via XWayland.")
            print("  Make sure XWayland is installed and running:")
            print("  Fedora: sudo dnf install xorg-x11-server-Xwayland")
        else:
            print("[eve-o-preview] ERROR: Wnck failed to get a default screen. Ensure X11/XWayland is available.")
        return
    app = EVEOPreview()
    # Closing the management window exits the application. Future optional
    # close-to-tray behavior should be handled by a tray setting instead of
    # overriding the close button unconditionally.
    def _on_destroy(_w):
        app.shutdown_hotkeys()
        Gtk.main_quit()
    app.connect("destroy", _on_destroy)
    # Also catch SIGINT/SIGTERM so kglobalaccel registrations don't leak
    # when the user kills the process from the terminal.
    import signal as _signal
    def _on_signal(_signum, _frame):
        try:
            app.shutdown_hotkeys()
        finally:
            Gtk.main_quit()
    for _sig in (_signal.SIGINT, _signal.SIGTERM):
        try:
            _signal.signal(_sig, _on_signal)
        except Exception:
            pass

    # Re-assert keep-above whenever the management window is (re-)mapped —
    # e.g. after un-minimising from the taskbar.  This ensures it appears
    # above any XWayland fullscreen EVE surface.
    def _on_app_map(widget):
        widget.set_keep_above(True)
        gdk_win = widget.get_window()
        if gdk_win:
            gdk_win.raise_()
    app.connect("map", _on_app_map)

    # Periodically re-assert keep-above so that if KDE strips the ABOVE flag
    # (e.g. when a fullscreen XWayland EVE window takes focus), the management
    # window eventually floats back.  A window-state-event handler would cause
    # an infinite feedback loop (set_keep_above → fires window-state-event →
    # set_keep_above → ...) that freezes the UI on alt-tab, so we use a timer.
    def _keep_app_above():
        try:
            gdk_win = app.get_window()
            if gdk_win and not (gdk_win.get_state() & Gdk.WindowState.ICONIFIED):
                app.set_keep_above(True)
        except Exception:
            pass
        return True  # keep repeating
    GLib.timeout_add(4000, _keep_app_above)

    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()