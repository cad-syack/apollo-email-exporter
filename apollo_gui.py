"""
Apollo Email Exporter - desktop GUI.

Exports emails of your saved Apollo contacts to a text file, page by page,
using Apollo's official API.

Build the .exe:
    pip install requests pyinstaller
    pyinstaller --onefile --windowed --name ApolloEmailExporter apollo_gui.py
"""

import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import requests

API_URL = "https://api.apollo.io/api/v1/contacts/search"
PER_PAGE = 100          # max Apollo allows per page
DELAY_SECONDS = 1.0     # stay well under Apollo's rate limits

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ApolloEmailExporter")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DEFAULT_OUTPUT = os.path.join(os.path.expanduser("~"), "Desktop", "apollo_emails.txt")


def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


def fetch_page(session, page, stop_event, log):
    for attempt in range(5):
        resp = session.post(API_URL, json={"page": page, "per_page": PER_PAGE}, timeout=30)
        if resp.status_code == 429:  # rate limited: back off and retry
            wait = 2 ** attempt * 5
            log(f"Rate limited, waiting {wait}s...")
            if stop_event.wait(wait):
                return None
            continue
        if resp.status_code in (401, 403):
            raise RuntimeError("Apollo rejected the API key (check the key and that your plan includes API access).")
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("Too many rate-limit retries")


def read_existing_emails(path):
    try:
        with open(path, encoding="utf-8") as f:
            return {line.strip().lower() for line in f if line.strip()}
    except OSError:
        return set()


def run_export(api_key, output_file, append, stop_event, events):
    """Runs in a worker thread; reports back to the UI through the events queue."""
    def log(msg):
        events.put(("log", msg))

    session = requests.Session()
    session.headers.update({
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
    })

    # In append mode, emails already in the file are skipped so each run only adds new ones
    seen = read_existing_emails(output_file) if append else set()
    already = len(seen)
    if append and already:
        log(f"{already} emails already in the file; adding only new ones.")
    added = 0
    page = 1
    try:
        if append and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            with open(output_file, "rb") as f:
                f.seek(-1, os.SEEK_END)
                needs_newline = f.read(1) != b"\n"
        else:
            needs_newline = False
        with open(output_file, "a" if append else "w", encoding="utf-8") as out:
            if needs_newline:
                out.write("\n")
            while not stop_event.is_set():
                data = fetch_page(session, page, stop_event, log)
                if data is None:
                    break
                contacts = data.get("contacts", [])
                total_pages = data.get("pagination", {}).get("total_pages", page) or 1

                new = 0
                for c in contacts:
                    email = (c.get("email") or "").strip().lower()
                    if email and email not in seen:
                        seen.add(email)
                        out.write(email + "\n")
                        new += 1
                added += new
                out.flush()
                log(f"Page {page}/{total_pages}: {new} new emails (total in file {len(seen)})")
                events.put(("progress", page, total_pages))

                if not contacts or page >= total_pages:
                    break
                page += 1
                if stop_event.wait(DELAY_SECONDS):
                    break

        if stop_event.is_set():
            log(f"Stopped. {added} new emails added so far ({len(seen)} in file).")
        else:
            log(f"Done. {added} new emails added; {len(seen)} total in {output_file}")
        events.put(("done", added, None))
    except Exception as e:  # report any failure to the UI instead of crashing the thread
        events.put(("done", added, str(e)))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Apollo Email Exporter")
        self.geometry("560x420")
        self.minsize(480, 360)

        cfg = load_config()
        self.api_key = tk.StringVar(value=cfg.get("api_key", ""))
        self.output = tk.StringVar(value=cfg.get("output", DEFAULT_OUTPUT))
        self.remember = tk.BooleanVar(value=bool(cfg.get("api_key")))
        self.append = tk.BooleanVar(value=cfg.get("append", True))
        self.show_key = tk.BooleanVar(value=False)

        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None

        self._build()
        self.after(100, self._poll_events)

    def _build(self):
        pad = {"padx": 10, "pady": 4}
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Apollo API key:").grid(row=0, column=0, sticky="w", **pad)
        self.key_entry = ttk.Entry(frm, textvariable=self.api_key, show="•")
        self.key_entry.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Checkbutton(frm, text="Show", variable=self.show_key,
                        command=self._toggle_key).grid(row=0, column=2, sticky="w")

        ttk.Checkbutton(frm, text="Remember API key on this PC",
                        variable=self.remember).grid(row=1, column=1, sticky="w", padx=10)

        ttk.Label(frm, text="Save emails to:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.output).grid(row=2, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Browse...", command=self._browse).grid(row=2, column=2, sticky="w")

        ttk.Checkbutton(frm, text="Only new contacts (add to the same file, skip emails already in it)",
                        variable=self.append).grid(row=3, column=0, columnspan=3, sticky="w", padx=10)

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=3, sticky="w", **pad)
        self.start_btn = ttk.Button(btns, text="Start export", command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btns, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self.open_btn = ttk.Button(btns, text="Open file", command=self._open_file)
        self.open_btn.pack(side="left")

        self.progress = ttk.Progressbar(frm, mode="determinate")
        self.progress.grid(row=5, column=0, columnspan=3, sticky="ew", **pad)

        self.status = ttk.Label(frm, text="Ready.")
        self.status.grid(row=6, column=0, columnspan=3, sticky="w", **pad)

        self.log_box = tk.Text(frm, height=10, state="disabled", wrap="word")
        self.log_box.grid(row=7, column=0, columnspan=3, sticky="nsew", **pad)
        frm.rowconfigure(7, weight=1)

    def _toggle_key(self):
        self.key_entry.configure(show="" if self.show_key.get() else "•")

    def _browse(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Text files", "*.txt")],
            initialfile=os.path.basename(self.output.get()) or "apollo_emails.txt")
        if path:
            self.output.set(path)

    def _log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _start(self):
        key = self.api_key.get().strip()
        out = self.output.get().strip()
        if not key:
            messagebox.showwarning("Missing API key", "Paste your Apollo API key first.")
            return
        if not out:
            messagebox.showwarning("Missing file", "Choose where to save the emails.")
            return

        cfg = {"output": out, "append": self.append.get()}
        if self.remember.get():
            cfg["api_key"] = key
        try:
            save_config(cfg)
        except OSError:
            pass  # remembering settings is a convenience; don't block the export

        self.stop_event.clear()
        self.progress["value"] = 0
        self.status.configure(text="Exporting...")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._log("Starting export...")
        self.worker = threading.Thread(
            target=run_export, args=(key, out, self.append.get(), self.stop_event, self.events), daemon=True)
        self.worker.start()

    def _stop(self):
        self.stop_event.set()
        self.status.configure(text="Stopping...")

    def _open_file(self):
        path = self.output.get().strip()
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showinfo("No file yet", "Run an export first.")

    def _poll_events(self):
        try:
            while True:
                ev = self.events.get_nowait()
                if ev[0] == "log":
                    self._log(ev[1])
                elif ev[0] == "progress":
                    _, page, total = ev
                    self.progress["maximum"] = total
                    self.progress["value"] = page
                    self.status.configure(text=f"Page {page} of {total}")
                elif ev[0] == "done":
                    _, count, error = ev
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    if error:
                        self.status.configure(text="Failed.")
                        self._log("Error: " + error)
                        messagebox.showerror("Export failed", error)
                    else:
                        self.status.configure(text=f"Finished: {count} new emails added.")
        except queue.Empty:
            pass
        self.after(100, self._poll_events)


if __name__ == "__main__":
    App().mainloop()
