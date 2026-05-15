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
        if self._window and self._window.winfo_exists():
            self._window.lift()
            self._window.focus_force()
            return

        self._window = tk.Tk()
        self._window.title("Clawdmeter - Claude Code Usage")
        self._window.configure(bg="#1a1a1a")
        self._window.resizable(False, False)
        self._window.overrideredirect(True)

        win_w, win_h = 400, 340
        sw = self._window.winfo_screenwidth()
        sh = self._window.winfo_screenheight()
        x = sw - win_w - 20
        y = 50
        self._window.geometry(f"{win_w}x{win_h}+{x}+{y}")

        container = tk.Frame(
            self._window, bg="#1a1a1a",
            highlightbackground="#2a2a2a", highlightthickness=1
        )
        container.pack(fill="both", expand=True)

        if data and data.get("ok"):
            peak = max(data["s"], data["w"])
        else:
            peak = 0

        accent_color = "#c0392b" if peak >= 80 else "#d97757" if peak >= 50 else "#788c5d"

        accent = tk.Frame(container, bg=accent_color, height=3)
        accent.pack(fill="x")
        accent.pack_propagate(False)

        title_bar = tk.Frame(container, bg="#202020", height=36)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)

        orb_frame = tk.Frame(title_bar, bg="#202020", width=16, height=16)
        orb_frame.pack(side="left", padx=(10, 6), pady=0)
        orb_frame.pack_propagate(False)
        orb_canvas = tk.Canvas(orb_frame, width=16, height=16, bg="#202020",
                               highlightthickness=0)
        orb_canvas.pack()
        orb_canvas.create_oval(2, 2, 14, 14, fill=accent_color, outline="")

        tk.Label(title_bar, text="Clawdmeter", bg="#202020", fg="#faf9f5",
                 font=("Segoe UI", 10, "bold")).pack(side="left")

        close_btn = tk.Label(title_bar, text="✕", bg="#202020", fg="#666666",
                             font=("Segoe UI", 12), cursor="hand2")
        close_btn.pack(side="right", padx=10)
        close_btn.bind("<Button-1>", lambda e: self._close())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg="#faf9f5"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg="#666666"))

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

        sep = tk.Frame(container, bg="#2a2a2a", height=1)
        sep.pack(fill="x")

        content = tk.Frame(container, bg="#1a1a1a", padx=24, pady=18)
        content.pack(fill="both", expand=True)

        if data and data.get("ok"):
            sp, wp = data["s"], data["w"]
            sr, wr = data["sr"], data["wr"]
            st = data["st"]

            def bar_color(p):
                return "#c0392b" if p >= 80 else "#d97757" if p >= 50 else "#788c5d"

            for label, pct, reset, color_args in [
                ("Session", sp, sr, {"fg": bar_color(sp)}),
                ("Weekly", wp, wr, {"fg": bar_color(wp)}),
            ]:
                card = tk.Frame(content, bg="#181818", highlightbackground="#242424",
                                highlightthickness=1)
                card.pack(fill="x", pady=(0, 12))

                card_inner = tk.Frame(card, bg="#181818", padx=16, pady=12)
                card_inner.pack(fill="x", expand=True)

                left_accent = tk.Frame(card_inner, bg=color_args["fg"], width=3)
                left_accent.pack(side="left", fill="y")
                left_accent.pack_propagate(False)

                body = tk.Frame(card_inner, bg="#181818")
                body.pack(side="left", fill="x", expand=True, padx=(14, 0))

                title_row = tk.Frame(body, bg="#181818")
                title_row.pack(fill="x")

                tk.Label(title_row, text=label, bg="#181818", fg="#b0aea5",
                         font=("Segoe UI", 10)).pack(side="left")

                sub_label = "5h session" if label == "Session" else "7d rolling"
                tk.Label(title_row, text=sub_label, bg="#181818", fg="#555555",
                         font=("Segoe UI", 8)).pack(side="left", padx=(6, 0))

                pct_row = tk.Frame(body, bg="#181818")
                pct_row.pack(fill="x", pady=(2, 0))

                canvas_size = 32
                cframe = tk.Frame(pct_row, bg="#181818", width=canvas_size,
                                  height=canvas_size)
                cframe.pack(side="left")
                cframe.pack_propagate(False)
                c = tk.Canvas(cframe, width=canvas_size, height=canvas_size,
                              bg="#181818", highlightthickness=0)
                c.pack()

                r = int((canvas_size / 2) - 3)
                cx_, cy_ = canvas_size // 2, canvas_size // 2
                c.create_oval(cx_ - r, cy_ - r, cx_ + r, cy_ + r,
                              outline="#2a2a2a", width=3)

                c.create_arc(
                    cx_ - r, cy_ - r, cx_ + r, cy_ + r,
                    start=90, extent=-int(360 * pct / 100),
                    outline=bar_color(pct), width=3, style="arc"
                )

                tk.Label(pct_row, text=f"{pct}%", bg="#181818",
                         fg=bar_color(pct),
                         font=("Segoe UI", 24, "bold")).pack(side="left", padx=(8, 0))

                bar_bg = tk.Frame(body, bg="#242424", height=6)
                bar_bg.pack(fill="x", pady=(6, 0))
                bar_bg.pack_propagate(False)

                bw = int((400 - 24 * 2 - 16 * 2 - 14) * pct / 100)
                fill_bar = tk.Frame(bar_bg, bg=bar_color(pct), width=bw)
                fill_bar.pack(side="left", fill="y")

                reset_text = f"resets in {reset}m" if reset > 0 else "resetting..."
                tk.Label(body, text=reset_text, bg="#181818", fg="#555555",
                         font=("Segoe UI", 8)).pack(anchor="e", pady=(3, 0))

            status_colors = {"allowed": "#788c5d", "warning": "#d97757", "blocked": "#c0392b"}
            sc = status_colors.get(st, "#b0aea5")
            status_frame = tk.Frame(content, bg="#1a1a1a")
            status_frame.pack(fill="x", pady=(0, 4))

            bulb = tk.Frame(status_frame, bg="#1a1a1a", width=10, height=10)
            bulb.pack(side="left")
            bulb.pack_propagate(False)
            bulb_c = tk.Canvas(bulb, width=10, height=10, bg="#1a1a1a",
                               highlightthickness=0)
            bulb_c.pack()
            bulb_c.create_oval(1, 1, 9, 9, fill=sc, outline="")

            tk.Label(status_frame, text=st.upper(), bg="#1a1a1a", fg=sc,
                     font=("Segoe UI", 10, "bold")).pack(side="left", padx=(5, 0))

            tk.Label(status_frame, text="Click Refresh Now to update",
                     bg="#1a1a1a", fg="#444444",
                     font=("Segoe UI", 8)).pack(side="right")
        else:
            tk.Label(content, text="No data available", bg="#1a1a1a", fg="#c0392b",
                     font=("Segoe UI", 22, "bold")).pack(expand=True)
            tk.Label(content, text="Check ~/.claude/.credentials.json",
                     bg="#1a1a1a", fg="#666666",
                     font=("Segoe UI", 10)).pack()

        self._window.after(100, self._fade_in)
        self._window.mainloop()

    def _fade_in(self):
        try:
            alpha = self._window.attributes("-alpha")
            if alpha < 1.0:
                self._window.attributes("-alpha", min(alpha + 1.0, 1.0))
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
