from __future__ import annotations

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from executor_core import LogTranslator, ScriptExecutor, WindowInfo, detect_optional_first_argument, detect_required_arguments, enumerate_windows, focus_window, scan_script


APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "executor_config.json"

LANGUAGES = {
    "en": "English",
    "da": "Dansk",
}

TEXT = {
    "en": {
        "subtitle": (
            "Run your Windows scripts without VS Code. When a script starts, the executor "
            "scans imports, creates the local environment and installs missing dependencies automatically."
        ),
        "language": "Language",
        "python_file": "1. Python file",
        "choose_file": "Choose file",
        "imports_default": "Choose a Python file. Imports and dependencies are handled automatically when the script starts.",
        "window": "2. Window",
        "refresh_list": "Refresh list",
        "focus": "Focus",
        "window_info": (
            "The selected window is focused before the script starts. HWND, title, PID and "
            "process name are also passed to the script as PY_EXECUTOR_WINDOW_* environment variables."
        ),
        "no_window": "(No window / run normally)",
        "run_script": "▶  Run script",
        "stop": "■  Stop",
        "ready": "Ready",
        "log": "Log",
        "clear": "Clear",
        "file_dialog_title": "Choose Python file",
        "all_files": "All files",
        "choose_file_first": "Choose a Python file first.",
        "file_missing": "The selected Python file does not exist.",
        "choose_py": "Choose a file with the .py extension.",
        "found": "Found",
        "installed_as": "Installed as",
        "checked_start": "checked automatically on start.",
        "no_external": "No external dependencies found.",
        "scan_failed": "Could not scan the file",
        "choose_window_first": "Choose a window first.",
        "focus_failed": "Windows did not allow the window to be focused. The script can still be started.",
        "scanning_imports": "Scanning imports...",
        "starting": "Starting",
        "scan_environment": "Scanning imports and checking local environment...",
        "dependency_check": "Automatic dependency check enabled.",
        "imports_found": "Imports found",
        "pip_packages": "Pip packages",
        "preparing_environment": "Preparing environment...",
        "running": "Running",
        "error": "Error",
        "stopped": "Stopped",
        "finished": "Finished",
        "running_close": "A script is still running. Stop it and close the application?",
        "uninstall_python": "Uninstall Python",
        "uninstall_title": "Uninstall Python",
        "uninstall_warning": (
            "This will close Python Executor and uninstall the Python version used by this app. "
            "It will also remove pip, user-installed Python libraries and all local executor environments.\n\n"
            "Other programs that depend on this Python installation may stop working. Continue?"
        ),
        "uninstall_confirm": "Are you absolutely sure? This action cannot be undone from Python Executor.",
        "ctrl_c_stop": "Global Ctrl+C detected. Stopping script...",
        "script_input_title": "Script input",
        "script_input_prompt": "The script is waiting for input.",
        "argument_title": "Command-line argument",
        "argument_prompt": "Enter {name}",
        "argument_cancelled": "Script start cancelled because a required command-line argument was not provided.",
        "optional_argument_title": "Optional command-line argument",
        "optional_argument_prompt": "Enter {name}. Leave blank to continue without it (for example, BPM mode).",
        "security_scan": "Scanning script for suspicious behavior...",
        "security_warning_title": "Potential backdoor detected",
        "security_warning_intro": (
            "Python Executor found behavior that can be associated with backdoors or malware. "
            "This is a heuristic scan and can produce false positives.\n\n"
        ),
        "security_warning_continue": "\n\nDo you want to continue and run the script anyway?",
        "security_clean": "Security scan: no suspicious backdoor patterns found.",
    },
    "da": {
        "subtitle": (
            "Kør dine Windows-scripts uden VS Code. Ved start scanner executoren imports, "
            "opretter det lokale miljø og installerer manglende dependencies automatisk."
        ),
        "language": "Sprog",
        "python_file": "1. Python-fil",
        "choose_file": "Vælg fil",
        "imports_default": "Vælg en Python-fil. Imports og dependencies håndteres automatisk ved start.",
        "window": "2. Window",
        "refresh_list": "Opdater liste",
        "focus": "Fokusér",
        "window_info": (
            "Det valgte vindue fokuseres før scriptet starter. HWND, titel, PID og "
            "procesnavn gives også til scriptet som PY_EXECUTOR_WINDOW_* environment variables."
        ),
        "no_window": "(Intet vindue / kør normalt)",
        "run_script": "▶  Kør script",
        "stop": "■  Stop",
        "ready": "Klar",
        "log": "Log",
        "clear": "Ryd",
        "file_dialog_title": "Vælg Python-fil",
        "all_files": "Alle filer",
        "choose_file_first": "Vælg først en Python-fil.",
        "file_missing": "Den valgte Python-fil findes ikke.",
        "choose_py": "Vælg en fil med .py-endelsen.",
        "found": "Fundet",
        "installed_as": "Installeres som",
        "checked_start": "kontrolleres automatisk ved start.",
        "no_external": "Ingen eksterne dependencies fundet.",
        "scan_failed": "Kunne ikke scanne filen",
        "choose_window_first": "Vælg et vindue først.",
        "focus_failed": "Windows tillod ikke at vinduet blev fokuseret. Scriptet kan stadig startes.",
        "scanning_imports": "Scanner imports...",
        "starting": "Starter",
        "scan_environment": "Scanner imports og kontrollerer lokalt miljø...",
        "dependency_check": "Automatisk dependency-kontrol aktiv.",
        "imports_found": "Imports fundet",
        "pip_packages": "Pip-pakker",
        "preparing_environment": "Forbereder miljø...",
        "running": "Kører",
        "error": "Fejl",
        "stopped": "Stoppet",
        "finished": "Afsluttet",
        "running_close": "Et script kører stadig. Stop det og luk programmet?",
        "uninstall_python": "Afinstaller Python",
        "uninstall_title": "Afinstaller Python",
        "uninstall_warning": (
            "Dette lukker Python Executor og afinstallerer den Python-version, som appen bruger. "
            "Det fjerner også pip, brugerinstallerede Python-libraries og alle lokale executor-miljøer.\n\n"
            "Andre programmer, der bruger denne Python-installation, kan stoppe med at virke. Fortsæt?"
        ),
        "uninstall_confirm": "Er du helt sikker? Handlingen kan ikke fortrydes fra Python Executor.",
        "ctrl_c_stop": "Global Ctrl+C registreret. Stopper script...",
        "script_input_title": "Script-input",
        "script_input_prompt": "Scriptet venter på input.",
        "argument_title": "Kommandolinje-argument",
        "argument_prompt": "Indtast {name}",
        "argument_cancelled": "Scriptstart blev annulleret, fordi et nødvendigt kommandolinje-argument ikke blev angivet.",
        "optional_argument_title": "Valgfrit kommandolinje-argument",
        "optional_argument_prompt": "Indtast {name}. Lad feltet være tomt for at fortsætte uden det (f.eks. BPM-tilstand).",
        "security_scan": "Scanner scriptet for mistænkelig adfærd...",
        "security_warning_title": "Mulig backdoor fundet",
        "security_warning_intro": (
            "Python Executor har fundet adfærd, som kan være forbundet med backdoors eller malware. "
            "Scanningen er heuristisk og kan give falske positiver.\n\n"
        ),
        "security_warning_continue": "\n\nVil du fortsætte og køre scriptet alligevel?",
        "security_clean": "Sikkerhedsscanning: ingen mistænkelige backdoor-mønstre fundet.",
    },
}


class ExecutorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Python Executor")
        self.geometry("980x690")
        self.minsize(820, 600)

        self.executor = ScriptExecutor(APP_DIR)
        self.windows: list[WindowInfo] = []
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._hotkey_stop_event = threading.Event()
        self.log_translator = LogTranslator(
            lambda line: self._post("translated_log", line)
        )

        self.language = "en"
        self.script_var = tk.StringVar()
        self.window_var = tk.StringVar()
        self.language_var = tk.StringVar(value=LANGUAGES[self.language])
        self.status_var = tk.StringVar(value=TEXT[self.language]["ready"])
        self.imports_var = tk.StringVar(value=TEXT[self.language]["imports_default"])

        self._configure_style()
        self._build_ui()
        self._load_config()
        self._apply_language(refresh_imports=False)
        self.refresh_windows()
        if self.script_var.get():
            self.preview_imports()

        self.after(80, self._drain_events)
        self._start_global_ctrl_c_watcher()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def t(self, key: str) -> str:
        return TEXT.get(self.language, TEXT["en"]).get(key, key)

    def _configure_style(self):
        self.configure(bg="#111318")
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=("Segoe UI", 10))
        style.configure("App.TFrame", background="#111318")
        style.configure("Card.TFrame", background="#1b1f27")
        style.configure(
            "Title.TLabel",
            background="#111318",
            foreground="#f5f7fb",
            font=("Segoe UI Semibold", 24),
        )
        style.configure("Sub.TLabel", background="#111318", foreground="#9ba6b7")
        style.configure(
            "CardTitle.TLabel",
            background="#1b1f27",
            foreground="#f3f5f8",
            font=("Segoe UI Semibold", 11),
        )
        style.configure("CardText.TLabel", background="#1b1f27", foreground="#aeb8c7")
        style.configure("Status.TLabel", background="#111318", foreground="#9ee6b3")
        style.configure("TButton", padding=(12, 8), font=("Segoe UI Semibold", 10))
        style.configure("Primary.TButton", padding=(16, 10))
        style.configure("Danger.TButton", padding=(16, 10))
        style.configure(
            "TEntry",
            fieldbackground="#252a34",
            foreground="#f5f7fb",
            insertcolor="#f5f7fb",
        )
        style.configure(
            "TCombobox",
            fieldbackground="#252a34",
            foreground="#f5f7fb",
            arrowcolor="#f5f7fb",
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#252a34")],
            foreground=[("readonly", "#f5f7fb")],
        )
        style.configure("Horizontal.TProgressbar", troughcolor="#252a34")

    def _build_ui(self):
        root = ttk.Frame(self, style="App.TFrame", padding=24)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root, style="App.TFrame")
        header.pack(fill="x")

        self.title_label = ttk.Label(header, text="Python Executor", style="Title.TLabel")
        self.title_label.pack(side="left", anchor="w")

        language_frame = ttk.Frame(header, style="App.TFrame")
        language_frame.pack(side="right", anchor="e")

        self.language_label = ttk.Label(
            language_frame,
            text=self.t("language"),
            style="Sub.TLabel",
        )
        self.language_label.pack(side="left", padx=(0, 8))

        self.language_combo = ttk.Combobox(
            language_frame,
            textvariable=self.language_var,
            values=list(LANGUAGES.values()),
            state="readonly",
            width=12,
        )
        self.language_combo.pack(side="left")
        self.language_combo.bind("<<ComboboxSelected>>", self._on_language_changed)

        self.subtitle_label = ttk.Label(
            root,
            text=self.t("subtitle"),
            style="Sub.TLabel",
            wraplength=900,
        )
        self.subtitle_label.pack(anchor="w", pady=(2, 18))

        file_card = ttk.Frame(root, style="Card.TFrame", padding=16)
        file_card.pack(fill="x", pady=(0, 12))

        self.file_title_label = ttk.Label(
            file_card,
            text=self.t("python_file"),
            style="CardTitle.TLabel",
        )
        self.file_title_label.pack(anchor="w")

        file_row = ttk.Frame(file_card, style="Card.TFrame")
        file_row.pack(fill="x", pady=(8, 6))

        self.file_entry = ttk.Entry(file_row, textvariable=self.script_var)
        self.file_entry.pack(side="left", fill="x", expand=True)

        self.choose_file_button = ttk.Button(
            file_row,
            text=self.t("choose_file"),
            command=self.choose_file,
        )
        self.choose_file_button.pack(side="left", padx=(8, 0))

        self.imports_label = ttk.Label(
            file_card,
            textvariable=self.imports_var,
            style="CardText.TLabel",
            wraplength=850,
        )
        self.imports_label.pack(anchor="w", pady=(2, 0))

        window_card = ttk.Frame(root, style="Card.TFrame", padding=16)
        window_card.pack(fill="x", pady=(0, 12))

        self.window_title_label = ttk.Label(
            window_card,
            text=self.t("window"),
            style="CardTitle.TLabel",
        )
        self.window_title_label.pack(anchor="w")

        window_row = ttk.Frame(window_card, style="Card.TFrame")
        window_row.pack(fill="x", pady=(8, 6))

        self.window_combo = ttk.Combobox(
            window_row,
            textvariable=self.window_var,
            state="readonly",
        )
        self.window_combo.pack(side="left", fill="x", expand=True)

        self.refresh_button = ttk.Button(
            window_row,
            text=self.t("refresh_list"),
            command=self.refresh_windows,
        )
        self.refresh_button.pack(side="left", padx=(8, 0))

        self.focus_button = ttk.Button(
            window_row,
            text=self.t("focus"),
            command=self.focus_selected_window,
        )
        self.focus_button.pack(side="left", padx=(8, 0))

        self.window_info_label = ttk.Label(
            window_card,
            text=self.t("window_info"),
            style="CardText.TLabel",
            wraplength=850,
        )
        self.window_info_label.pack(anchor="w")

        controls = ttk.Frame(root, style="App.TFrame")
        controls.pack(fill="x", pady=(2, 12))

        self.run_button = ttk.Button(
            controls,
            text=self.t("run_script"),
            style="Primary.TButton",
            command=self.run_script,
        )
        self.run_button.pack(side="left")

        self.stop_button = ttk.Button(
            controls,
            text=self.t("stop"),
            style="Danger.TButton",
            command=self.stop_script,
            state="disabled",
        )
        self.stop_button.pack(side="left", padx=(8, 0))

        self.uninstall_button = ttk.Button(
            controls,
            text=self.t("uninstall_python"),
            command=self.uninstall_python,
        )
        self.uninstall_button.pack(side="left", padx=(8, 0))

        self.progress = ttk.Progressbar(controls, mode="indeterminate", length=150)
        self.progress.pack(side="right")

        self.status_label = ttk.Label(
            controls,
            textvariable=self.status_var,
            style="Status.TLabel",
        )
        self.status_label.pack(side="right", padx=(0, 12))

        log_card = ttk.Frame(root, style="Card.TFrame", padding=12)
        log_card.pack(fill="both", expand=True)

        log_header = ttk.Frame(log_card, style="Card.TFrame")
        log_header.pack(fill="x", pady=(0, 8))

        self.log_title_label = ttk.Label(
            log_header,
            text=self.t("log"),
            style="CardTitle.TLabel",
        )
        self.log_title_label.pack(side="left")

        self.clear_button = ttk.Button(
            log_header,
            text=self.t("clear"),
            command=self.clear_log,
        )
        self.clear_button.pack(side="right")

        text_wrap = ttk.Frame(log_card, style="Card.TFrame")
        text_wrap.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(text_wrap)
        scrollbar.pack(side="right", fill="y")

        self.log_text = tk.Text(
            text_wrap,
            wrap="word",
            bg="#0d0f13",
            fg="#d7dde7",
            insertbackground="#d7dde7",
            selectbackground="#39465c",
            relief="flat",
            padx=12,
            pady=10,
            font=("Cascadia Mono", 9),
            yscrollcommand=scrollbar.set,
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.log_text.yview)
        self.log_text.configure(state="disabled")

    def _on_language_changed(self, _event=None):
        selected_name = self.language_var.get()
        self.language = next(
            (code for code, name in LANGUAGES.items() if name == selected_name),
            "en",
        )
        self._apply_language(refresh_imports=True)
        self._save_config()

    def _apply_language(self, refresh_imports: bool = True):
        self.language_var.set(LANGUAGES.get(self.language, LANGUAGES["en"]))

        self.language_label.configure(text=self.t("language"))
        self.subtitle_label.configure(text=self.t("subtitle"))
        self.file_title_label.configure(text=self.t("python_file"))
        self.choose_file_button.configure(text=self.t("choose_file"))
        self.window_title_label.configure(text=self.t("window"))
        self.refresh_button.configure(text=self.t("refresh_list"))
        self.focus_button.configure(text=self.t("focus"))
        self.window_info_label.configure(text=self.t("window_info"))
        self.run_button.configure(text=self.t("run_script"))
        self.stop_button.configure(text=self.t("stop"))
        self.uninstall_button.configure(text=self.t("uninstall_python"))
        self.log_title_label.configure(text=self.t("log"))
        self.clear_button.configure(text=self.t("clear"))

        if not self.executor.process or self.executor.process.poll() is not None:
            self.status_var.set(self.t("ready"))

        self._refresh_window_values()

        if refresh_imports:
            if self.script_var.get().strip():
                self.preview_imports()
            else:
                self.imports_var.set(self.t("imports_default"))

    def _post(self, event: str, value: object = None):
        self.events.put((event, value))

    def _drain_events(self):
        try:
            while True:
                event, value = self.events.get_nowait()

                if event == "log":
                    self.log_translator.submit(str(value), self.language)
                elif event == "translated_log":
                    self._append_log(str(value))
                elif event == "status":
                    self.status_var.set(str(value))
                elif event == "busy":
                    self._set_busy(bool(value))
                elif event == "imports":
                    self.imports_var.set(str(value))
                elif event == "error":
                    messagebox.showerror("Python Executor", str(value))
                elif event == "finished":
                    self._set_busy(False)
                    self.status_var.set(f"{self.t('finished')} ({value})")
                elif event == "global_ctrl_c":
                    if self.executor.process and self.executor.process.poll() is None:
                        self.log(self.t("ctrl_c_stop"))
                        self.stop_script()
                elif event == "input_request":
                    prompt, response_queue = value
                    shown_prompt = str(prompt).strip() or self.t("script_input_prompt")
                    answer = simpledialog.askstring(
                        self.t("script_input_title"),
                        shown_prompt,
                        parent=self,
                    )
                    response_queue.put("" if answer is None else answer)
        except queue.Empty:
            pass

        self.after(80, self._drain_events)

    def _start_global_ctrl_c_watcher(self):
        if os.name != "nt":
            return

        def watch():
            user32 = ctypes.windll.user32
            VK_CONTROL = 0x11
            VK_C = 0x43
            was_pressed = False

            while not self._hotkey_stop_event.is_set():
                ctrl_down = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
                c_down = bool(user32.GetAsyncKeyState(VK_C) & 0x8000)
                pressed = ctrl_down and c_down

                if pressed and not was_pressed:
                    process = self.executor.process
                    if process and process.poll() is None:
                        self._post("global_ctrl_c")

                was_pressed = pressed
                self._hotkey_stop_event.wait(0.03)

        threading.Thread(
            target=watch,
            name="GlobalCtrlCWatcher",
            daemon=True,
        ).start()

    def _append_log(self, line: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def log(self, line: str):
        self.log_translator.submit(str(line), self.language)

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_busy(self, busy: bool):
        if busy:
            self.run_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            self.progress.start(12)
        else:
            self.run_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.progress.stop()

    def choose_file(self):
        path = filedialog.askopenfilename(
            title=self.t("file_dialog_title"),
            filetypes=[("Python files", "*.py"), (self.t("all_files"), "*.*")],
        )
        if not path:
            return

        self.script_var.set(path)
        self.preview_imports()
        self._save_config()

    def _script_path(self, show_errors: bool = True) -> Path | None:
        raw = self.script_var.get().strip().strip('"')

        if not raw:
            if show_errors:
                messagebox.showwarning("Python Executor", self.t("choose_file_first"))
            return None

        path = Path(raw)

        if not path.is_file():
            if show_errors:
                messagebox.showerror("Python Executor", self.t("file_missing"))
            return None

        if path.suffix.lower() != ".py":
            if show_errors:
                messagebox.showwarning("Python Executor", self.t("choose_py"))
            return None

        return path

    def preview_imports(self):
        path = self._script_path(show_errors=False)
        if not path:
            self.imports_var.set(self.t("imports_default"))
            return

        try:
            imports = self.executor.external_imports(path)

            if imports:
                packages = [self.executor.package_for_import(item) for item in imports]
                text = f"{self.t('found')}: " + ", ".join(imports)

                if packages != imports:
                    text += f"  |  {self.t('installed_as')}: " + ", ".join(packages)

                text += f"  —  {self.t('checked_start')}"
            else:
                text = self.t("no_external")

            self.imports_var.set(text)
        except Exception as exc:
            self.imports_var.set(f"{self.t('scan_failed')}: {exc}")

    def _refresh_window_values(self):
        selected = self.selected_window()
        current_hwnd = selected.hwnd if selected else None

        values = [self.t("no_window")] + [
            window.display_name for window in self.windows
        ]
        self.window_combo["values"] = values

        index = 0
        if current_hwnd:
            for i, window in enumerate(self.windows, start=1):
                if window.hwnd == current_hwnd:
                    index = i
                    break

        if values:
            self.window_combo.current(index)

    def refresh_windows(self):
        selected = self.selected_window()
        current_hwnd = selected.hwnd if selected else None

        self.windows = enumerate_windows()

        values = [self.t("no_window")] + [
            window.display_name for window in self.windows
        ]
        self.window_combo["values"] = values

        index = 0
        if current_hwnd:
            for i, window in enumerate(self.windows, start=1):
                if window.hwnd == current_hwnd:
                    index = i
                    break

        if values:
            self.window_combo.current(index)

        self._save_config()

    def selected_window(self) -> WindowInfo | None:
        index = self.window_combo.current()

        if index <= 0:
            return None

        actual = index - 1
        if 0 <= actual < len(self.windows):
            return self.windows[actual]

        return None

    def focus_selected_window(self):
        window = self.selected_window()

        if not window:
            messagebox.showinfo("Python Executor", self.t("choose_window_first"))
            return

        if not focus_window(window.hwnd):
            messagebox.showwarning(
                "Python Executor",
                self.t("focus_failed"),
            )

    def request_script_input(self, prompt: str) -> str:
        response_queue: queue.Queue[str] = queue.Queue(maxsize=1)
        self._post("input_request", (prompt, response_queue))
        return response_queue.get()

    def run_script(self):
        path = self._script_path()
        if not path:
            return

        try:
            expected_script_hash = self.executor.script_sha256(path)
            self.log(f"Source integrity baseline: {path.name} [{expected_script_hash[:12]}]")
            argument_specs = detect_required_arguments(path)
            optional_first_argument = detect_optional_first_argument(path)
            self.executor.verify_script_integrity(
                path,
                expected_script_hash,
                "after argument detection",
                self.log,
            )
        except Exception as exc:
            messagebox.showerror("Python Executor", str(exc))
            self.status_var.set(self.t("error"))
            return

        arguments: list[str] = []

        if optional_first_argument and not argument_specs:
            label = optional_first_argument.replace("_", " ")
            answer = simpledialog.askstring(
                self.t("optional_argument_title"),
                self.t("optional_argument_prompt").format(name=label),
                parent=self,
            )
            if answer is not None and answer.strip():
                arguments.append(answer.strip())

        for spec in argument_specs:
            label = spec.name.replace("_", " ")
            answer = simpledialog.askstring(
                self.t("argument_title"),
                self.t("argument_prompt").format(name=label),
                parent=self,
            )
            if answer is None:
                self.status_var.set(self.t("ready"))
                self.log(self.t("argument_cancelled"))
                return
            arguments.append(answer)

        self.status_var.set(self.t("security_scan"))
        findings = scan_script(path)

        try:
            self.executor.verify_script_integrity(
                path,
                expected_script_hash,
                "after security scan",
                self.log,
            )
        except Exception as exc:
            messagebox.showerror("Python Executor", str(exc))
            self.status_var.set(self.t("error"))
            return

        if findings:
            details = "\n\n".join(finding.display() for finding in findings[:12])
            if len(findings) > 12:
                details += f"\n\n... +{len(findings) - 12} more finding(s)"

            proceed = messagebox.askyesno(
                self.t("security_warning_title"),
                self.t("security_warning_intro")
                + details
                + self.t("security_warning_continue"),
                icon="warning",
            )
            if not proceed:
                self.status_var.set(self.t("ready"))
                return
        else:
            self.log(self.t("security_clean"))

        window = self.selected_window()

        self._save_config()
        self._set_busy(True)
        self.status_var.set(self.t("scanning_imports"))
        self.log("")
        self.log(f"=== {self.t('starting')} {path.name} ===")
        self.log(self.t("scan_environment"))

        def prepare_and_run():
            try:
                imports = self.executor.external_imports(path)
                self.executor.verify_script_integrity(
                    path,
                    expected_script_hash,
                    "after import scan",
                    self.log,
                )

                if imports:
                    packages = [self.executor.package_for_import(item) for item in imports]
                    self._post(
                        "imports",
                        f"{self.t('found')}: "
                        + ", ".join(imports)
                        + f"  |  {self.t('dependency_check')}",
                    )
                    self.log(f"{self.t('imports_found')}: " + ", ".join(imports))
                    self.log(f"{self.t('pip_packages')}: " + ", ".join(packages))
                else:
                    self._post("imports", self.t("no_external"))
                    self.log(self.t("no_external"))

                self._post("status", self.t("preparing_environment"))

                self.executor.start_script(
                    path,
                    window,
                    self.log,
                    lambda code: self._post("finished", code),
                    self.request_script_input,
                    arguments,
                    expected_script_hash,
                )

                self._post("status", self.t("running"))
            except Exception as exc:
                self._post("error", str(exc))
                self._post("status", self.t("error"))
                self._post("busy", False)

        threading.Thread(target=prepare_and_run, daemon=True).start()

    def stop_script(self):
        if self.executor.stop_script(self.log):
            self.status_var.set(self.t("stopped"))

        self._set_busy(False)

    def uninstall_python(self):
        if self.executor.process and self.executor.process.poll() is None:
            messagebox.showwarning(
                "Python Executor",
                self.t("running_close"),
            )
            return

        if not messagebox.askyesno(
            self.t("uninstall_title"),
            self.t("uninstall_warning"),
            icon="warning",
        ):
            return

        if not messagebox.askyesno(
            self.t("uninstall_title"),
            self.t("uninstall_confirm"),
            icon="warning",
        ):
            return

        uninstaller = APP_DIR / "uninstall" / "uninstall_python.bat"
        if not uninstaller.is_file():
            messagebox.showerror(
                "Python Executor",
                f"Uninstaller not found: {uninstaller}",
            )
            return

        self._save_config()

        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        pid = os.getpid()

        try:
            os.startfile(
                str(uninstaller),
                arguments=f'{pid} {version} "{APP_DIR}"',
                show_cmd=1,
            )
        except TypeError:
            subprocess.Popen(
                [
                    "cmd.exe",
                    "/c",
                    "start",
                    "",
                    str(uninstaller),
                    str(pid),
                    version,
                    str(APP_DIR),
                ],
                cwd=str(APP_DIR),
            )
        except OSError as exc:
            messagebox.showerror("Python Executor", str(exc))
            return

        self.destroy()

    def _save_config(self):
        selected = self.selected_window()

        data = {
            "language": self.language,
            "last_script": self.script_var.get().strip(),
            "last_window_title": selected.title if selected else "",
            "last_window_process": selected.process_name if selected else "",
        }

        try:
            CONFIG_FILE.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _load_config(self):
        if not CONFIG_FILE.exists():
            self.language = "en"
            self.language_var.set(LANGUAGES["en"])
            return

        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

            saved_language = data.get("language", "en")
            self.language = saved_language if saved_language in LANGUAGES else "en"
            self.language_var.set(LANGUAGES[self.language])

            script = data.get("last_script", "")
            if script and Path(script).is_file():
                self.script_var.set(script)

        except (OSError, json.JSONDecodeError):
            self.language = "en"
            self.language_var.set(LANGUAGES["en"])

    def _on_close(self):
        self._hotkey_stop_event.set()
        self.log_translator.close()

        if self.executor.process and self.executor.process.poll() is None:
            if not messagebox.askyesno(
                "Python Executor",
                self.t("running_close"),
            ):
                return

            self.executor.stop_script(self.log)

        self._save_config()
        self.destroy()


if __name__ == "__main__":
    app = ExecutorApp()
    app.mainloop()