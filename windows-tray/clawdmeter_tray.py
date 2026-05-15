"""Clawdmeter Windows Traybar App
Polls Claude Code API usage and displays in system tray.
"""

import json
import os
import re
import signal
import sys
import threading
import time
from pathlib import Path

import httpx
import pystray
from PIL import Image, ImageDraw, ImageFont


DEVICE_NAME = "Claude Controller"
POLL_INTERVAL = 60
TICK = 5

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"

API_URL = "https://api.anthropic.com/v1/messages"
API_HEADERS_TEMPLATE = {
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "oauth-2025-04-20",
    "Content-Type": "application/json",
    "User-Agent": "claude-code/2.1.5",
}
API_BODY = {
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 1,
    "messages": [{"role": "user", "content": "hi"}],
}


def read_token() -> str | None:
    try:
        raw = CREDENTIALS_PATH.read_text()
    except OSError:
        return None
    m = re.search(r'"accessToken"\s*:\s*"([^"]+)"', raw)
    if m:
        return m.group(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        if isinstance(data.get("accessToken"), str):
            return data["accessToken"]
        for v in data.values():
            if isinstance(v, dict) and isinstance(v.get("accessToken"), str):
                return v["accessToken"]
    return None


def poll_api(token: str) -> dict | None:
    headers = dict(API_HEADERS_TEMPLATE)
    headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.post(API_URL, headers=headers, json=API_BODY, timeout=20.0)
    except httpx.HTTPError:
        return None

    def hdr(name: str, default: str = "0") -> str:
        return resp.headers.get(name, default)

    now = time.time()

    def reset_minutes(reset_ts: str) -> int:
        try:
            r = float(reset_ts)
        except ValueError:
            return 0
        mins = (r - now) / 60.0
        return int(round(mins)) if mins > 0 else 0

    def pct(util: str) -> int:
        try:
            return int(round(float(util) * 100))
        except ValueError:
            return 0

    return {
        "s": pct(hdr("anthropic-ratelimit-unified-5h-utilization")),
        "sr": reset_minutes(hdr("anthropic-ratelimit-unified-5h-reset")),
        "w": pct(hdr("anthropic-ratelimit-unified-7d-utilization")),
        "wr": reset_minutes(hdr("anthropic-ratelimit-unified-7d-reset")),
        "st": hdr("anthropic-ratelimit-unified-5h-status", "unknown"),
        "ok": True,
    }


def _status_color(p: int):
    if p >= 80:
        return (192, 57, 43)
    if p >= 50:
        return (217, 119, 87)
    return (120, 140, 93)


def create_tray_image(session_pct: int, weekly_pct: int) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    peak = max(session_pct, weekly_pct)
    r, g, b = _status_color(peak)

    cx, cy = size // 2, size // 2
    radius = 22

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for i in range(8, 0, -1):
        a = int(28 / (8 - i + 1))
        gdraw.ellipse(
            (cx - radius - i, cy - radius - i, cx + radius + i, cy + radius + i),
            fill=(r, g, b, a),
        )

    inner = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    idraw = ImageDraw.Draw(inner)

    idraw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=(r, g, b),
    )

    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hdraw = ImageDraw.Draw(highlight)
    hdraw.ellipse(
        (cx - radius + 2, cy - radius + 2, cx + 2, cy + 2),
        fill=(255, 255, 255, 55),
    )

    img = Image.alpha_composite(img, glow)
    img = Image.alpha_composite(img, inner)
    img = Image.alpha_composite(img, highlight)

    draw = ImageDraw.Draw(img)
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=(0, 0, 0, 60),
        width=1,
    )

    return img


class DashboardWindow:
    def __init__(self):
        self.root = None
        self._window = None

    def show(self, data: dict | None):
        import tkinter as tk
        from tkinter import ttk
        if self._window and self._window.winfo_exists():
            self._window.lift()
            self._window.focus_force()
            return

        self._window = tk.Tk()
        self._window.title("Clawdmeter - Claude Code Usage")
        self._window.configure(bg="#1a1a1a")
        self._window.resizable(False, False)
        self._window.overrideredirect(True)

        win_w, win_h = 380, 320
        sw = self._window.winfo_screenwidth()
        sh = self._window.winfo_screenheight()
        x = sw - win_w - 20
        y = 50
        self._window.geometry(f"{win_w}x{win_h}+{x}+{y}")

        container = tk.Frame(self._window, bg="#1a1a1a", highlightbackground="#333333", highlightthickness=1)
        container.pack(fill="both", expand=True)

        title_bar = tk.Frame(container, bg="#2a2a2a", height=32)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)

        tk.Label(title_bar, text="Clawdmeter", bg="#2a2a2a", fg="#faf9f5",
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=10, pady=4)

        close_btn = tk.Label(title_bar, text="✕", bg="#2a2a2a", fg="#b0aea5",
                             font=("Segoe UI", 12), cursor="hand2")
        close_btn.pack(side="right", padx=10, pady=4)
        close_btn.bind("<Button-1>", lambda e: self._close())

        def start_move(event):
            self._window.x = event.x
            self._window.y = event.y

        def do_move(event):
            dx = event.x - self._window.x
            dy = event.y - self._window.y
            x = self._window.winfo_x() + dx
            y = self._window.winfo_y() + dy
            self._window.geometry(f"+{x}+{y}")

        title_bar.bind("<Button-1>", start_move)
        title_bar.bind("<B1-Motion>", do_move)

        content = tk.Frame(container, bg="#1a1a1a", padx=20, pady=16)
        content.pack(fill="both", expand=True)

        font_lg = ("Segoe UI", 28, "bold")
        font_md = ("Segoe UI", 11)
        font_sm = ("Segoe UI", 9)

        if data and data.get("ok"):
            sp, wp = data["s"], data["w"]
            sr, wr = data["sr"], data["wr"]
            st = data["st"]

            def bar_color(p):
                return "#c0392b" if p >= 80 else "#d97757" if p >= 50 else "#788c5d"

            row1 = tk.Frame(content, bg="#1a1a1a")
            row1.pack(fill="x", pady=(0, 4))

            tk.Label(row1, text="Session (5h)", bg="#1a1a1a", fg="#b0aea5",
                     font=font_md).pack(anchor="w")

            pct_frame = tk.Frame(row1, bg="#1a1a1a")
            pct_frame.pack(fill="x")

            tk.Label(pct_frame, text=f"{sp}%", bg="#1a1a1a", fg=bar_color(sp),
                     font=font_lg).pack(side="left")

            tk.Label(pct_frame, text=f"resets in {sr}m" if sr > 0 else "resetting...",
                     bg="#1a1a1a", fg="#666666", font=font_sm).pack(side="right", anchor="s")

            bar_frame = tk.Frame(content, bg="#333333", height=8)
            bar_frame.pack(fill="x", pady=(0, 16))
            bar_frame.pack_propagate(False)

            fill = tk.Frame(bar_frame, bg=bar_color(sp), width=int(380 * sp / 100))
            fill.pack(side="left", fill="y")

            row2 = tk.Frame(content, bg="#1a1a1a")
            row2.pack(fill="x", pady=(0, 4))

            tk.Label(row2, text="Weekly (7d)", bg="#1a1a1a", fg="#b0aea5",
                     font=font_md).pack(anchor="w")

            pct_frame2 = tk.Frame(row2, bg="#1a1a1a")
            pct_frame2.pack(fill="x")

            tk.Label(pct_frame2, text=f"{wp}%", bg="#1a1a1a", fg=bar_color(wp),
                     font=font_lg).pack(side="left")

            tk.Label(pct_frame2, text=f"resets in {wr}m" if wr > 0 else "resetting...",
                     bg="#1a1a1a", fg="#666666", font=font_sm).pack(side="right", anchor="s")

            bar_frame2 = tk.Frame(content, bg="#333333", height=8)
            bar_frame2.pack(fill="x", pady=(0, 16))
            bar_frame2.pack_propagate(False)

            fill2 = tk.Frame(bar_frame2, bg=bar_color(wp), width=int(380 * wp / 100))
            fill2.pack(side="left", fill="y")

            status_colors = {"allowed": "#788c5d", "warning": "#d97757", "blocked": "#c0392b"}
            sc = status_colors.get(st, "#b0aea5")
            status_frame = tk.Frame(content, bg="#1a1a1a")
            status_frame.pack(fill="x")

            tk.Label(status_frame, text="Status:", bg="#1a1a1a", fg="#b0aea5",
                     font=font_md).pack(side="left")

            tk.Label(status_frame, text=st.upper(), bg="#1a1a1a", fg=sc,
                     font=("Segoe UI", 11, "bold")).pack(side="left", padx=(8, 0))

            tk.Label(content, text="Click tray icon → Show Dashboard to refresh",
                     bg="#1a1a1a", fg="#555555", font=font_sm).pack(side="bottom", pady=(8, 0))
        else:
            tk.Label(content, text="No data available", bg="#1a1a1a", fg="#c0392b",
                     font=font_lg).pack(expand=True)
            tk.Label(content, text="Check your API token in ~/.claude/.credentials.json",
                     bg="#1a1a1a", fg="#666666", font=font_sm).pack()

        self._window.after(100, self._fade_in)
        self._window.mainloop()

    def _fade_in(self):
        try:
            alpha = self._window.attributes("-alpha")
            if alpha < 1.0:
                self._window.attributes("-alpha", min(alpha + 0.1, 1.0))
                self._window.after(30, self._fade_in)
        except tk.TclError:
            pass

    def _close(self):
        if self._window:
            self._window.destroy()
            self._window = None


class ClawdmeterTray:
    def __init__(self):
        self.data = None
        self.running = True
        self.icon = None
        self.poll_thread = None
        self.dashboard = DashboardWindow()
        self.last_data = None
        self._first_poll = True

    def on_refresh(self, icon, item):
        threading.Thread(target=self._do_poll, daemon=True).start()

    def on_show(self, icon, item):
        t = threading.Thread(target=self.dashboard.show, args=(self.last_data,), daemon=True)
        t.start()

    def on_open_claude(self, icon, item):
        os.startfile("claude") if sys.platform == "win32" else None

    def on_exit(self, icon, item):
        self.running = False
        if self.icon:
            self.icon.stop()

    def _do_poll(self):
        token = read_token()
        if not token:
            return
        data = poll_api(token)
        if data:
            self.last_data = data
            self._update_icon(data)

    def _update_icon(self, data):
        if self.icon:
            img = create_tray_image(data["s"], data["w"])
            self.icon.icon = img
            sp, wp = data["s"], data["w"]
            st = data["st"]
            self.icon.title = f"Clawdmeter | Session: {sp}% | Weekly: {wp}% | {st}"

    def _poll_loop(self):
        backoff = 1
        while self.running:
            token = read_token()
            if token:
                data = poll_api(token)
                if data:
                    self.last_data = data
                    self._update_icon(data)
                    if self._first_poll:
                        self._first_poll = False
                        t = threading.Thread(target=self.dashboard.show, args=(data,), daemon=True)
                        t.start()
                    backoff = 1
                else:
                    backoff = min(backoff * 2, 60)
            else:
                backoff = min(backoff * 2, 60)

            for _ in range(POLL_INTERVAL // TICK):
                if not self.running:
                    return
                time.sleep(TICK)

    def run(self):
        img = create_tray_image(0, 0)
        menu = pystray.Menu(
            pystray.MenuItem("Show Dashboard", self.on_show),
            pystray.MenuItem("Refresh Now", self.on_refresh),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Claude Code", self.on_open_claude),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self.on_exit),
        )
        self.icon = pystray.Icon("clawdmeter", img, "Clawdmeter", menu)

        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

        self.icon.run()


if __name__ == "__main__":
    app = ClawdmeterTray()
    app.run()
