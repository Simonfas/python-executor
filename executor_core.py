from __future__ import annotations

import ast
import builtins
import ctypes
import hashlib
import json
import os
import queue
import re
import runpy
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import venv
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


IS_WINDOWS = os.name == "nt"


IMPORT_TO_PACKAGE = {
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "Crypto": "pycryptodome",
    "dotenv": "python-dotenv",
    "serial": "pyserial",
    "win32api": "pywin32",
    "win32con": "pywin32",
    "win32gui": "pywin32",
    "win32process": "pywin32",
    "win32com": "pywin32",
    "pythoncom": "pywin32",
    "requests_html": "requests-html",
    "dateutil": "python-dateutil",
    "googleapiclient": "google-api-python-client",
}


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    pid: int
    process_name: str

    @property
    def display_name(self) -> str:
        proc = self.process_name or f"PID {self.pid}"
        return f"{self.title}: {proc}  [HWND {self.hwnd}]"


class DependencyError(RuntimeError):
    pass


class ScriptIntegrityError(RuntimeError):
    pass


class ScriptExecutor:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parent)
        self.env_root = self.base_dir / ".executor_envs"
        self.env_root.mkdir(parents=True, exist_ok=True)
        self.process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def script_sha256(self, script_path: str | Path) -> str:
        path = Path(script_path).resolve()
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def verify_script_integrity(
        self,
        script_path: str | Path,
        expected_hash: str,
        stage: str,
        log: Callable[[str], None] | None = None,
    ) -> None:
        path = Path(script_path).resolve()
        try:
            current_hash = self.script_sha256(path)
        except OSError as exc:
            raise ScriptIntegrityError(
                f"Source integrity check failed at '{stage}': {path.name} could not be read: {exc}"
            ) from exc

        if current_hash != expected_hash:
            raise ScriptIntegrityError(
                f"Source integrity violation at '{stage}': {path.name} changed before execution. "
                f"Expected SHA-256 {expected_hash}, got {current_hash}. Script start was blocked."
            )

        if log:
            log(f"Source integrity OK: {stage} [{current_hash[:12]}]")

    def env_dir_for_script(self, script_path: str | Path) -> Path:
        return self.env_root / "shared"

    def python_for_env(self, env_dir: Path) -> Path:
        if IS_WINDOWS:
            return env_dir / "Scripts" / "python.exe"
        return env_dir / "bin" / "python"

    def pip_for_env(self, env_dir: Path) -> list[str]:
        return [str(self.python_for_env(env_dir)), "-m", "pip"]

    def _get_pip_version(self, python_exe: Path) -> str:
        result = subprocess.run(
            [str(python_exe), "-m", "pip", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
        )
        if result.returncode != 0:
            return ""

        match = re.search(r"^pip\\s+([^\\s]+)", result.stdout.strip())
        return match.group(1) if match else ""

    def update_installed_libraries(
        self,
        env_dir: Path,
        log: Callable[[str], None],
    ) -> None:
        python_exe = self.python_for_env(env_dir)

        log("New pip version detected. Checking installed libraries for updates...")

        outdated_result = subprocess.run(
            [
                str(python_exe),
                "-m",
                "pip",
                "list",
                "--outdated",
                "--format=json",
                "--disable-pip-version-check",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
        )

        if outdated_result.returncode != 0:
            log("Warning: Could not check installed libraries for updates.")
            return

        try:
            outdated = json.loads(outdated_result.stdout or "[]")
        except json.JSONDecodeError:
            log("Warning: pip returned an invalid response while checking library updates.")
            return

        packages = []
        ignored = {"pip"}
        for item in outdated:
            name = str(item.get("name", "")).strip()
            if name and self._normalize_package_name(name) not in ignored:
                packages.append(name)

        if not packages:
            log("All installed libraries are already up to date.")
            self.build_library_cache(env_dir, log)
            return

        log("Updating installed libraries: " + ", ".join(packages))

        process = subprocess.Popen(
            [
                str(python_exe),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--disable-pip-version-check",
                "--no-cache-dir",
                *packages,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
        )

        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip()
            if line:
                log(line)

        code = process.wait()
        if code != 0:
            log("Warning: One or more libraries could not be updated.")
        else:
            log("Installed libraries updated successfully.")

        self.build_library_cache(env_dir, log)

    def update_pip(self, env_dir: Path, log: Callable[[str], None]) -> None:
        python_exe = self.python_for_env(env_dir)

        if not python_exe.exists():
            raise DependencyError("Python executable is missing from the local environment.")

        log("Checking pip for updates...")

        subprocess.run(
            [str(python_exe), "-m", "ensurepip", "--upgrade"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
        )

        old_version = self._get_pip_version(python_exe)

        process = subprocess.Popen(
            [
                str(python_exe),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "pip",
                "--disable-pip-version-check",
                "--no-cache-dir",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
        )

        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip()
            if line:
                log(line)

        code = process.wait()
        if code != 0:
            log("Warning: pip update check failed. Continuing with the installed pip version.")
            return

        new_version = self._get_pip_version(python_exe)

        if new_version:
            log(f"pip ready: {new_version}")

        if old_version and new_version and old_version != new_version:
            log(f"pip was updated from {old_version} to {new_version}.")
            self.update_installed_libraries(env_dir, log)
        elif not old_version and new_version:
            self.build_library_cache(env_dir, log)
        else:
            log("pip is already up to date.")

    def ensure_env(self, script_path: str | Path, log: Callable[[str], None]) -> Path:
        env_dir = self.env_dir_for_script(script_path)
        python_exe = self.python_for_env(env_dir)

        if not python_exe.exists():
            log(f"Creating shared Python environment: {env_dir}")
            try:
                venv.EnvBuilder(with_pip=True, clear=False).create(env_dir)
            except Exception as exc:
                raise DependencyError(f"Could not create shared Python environment: {exc}") from exc

            if not python_exe.exists():
                raise DependencyError("The shared Python environment was created, but python.exe is missing.")

        self.update_pip(env_dir, log)
        return env_dir

    def parse_imports(self, script_path: str | Path) -> list[str]:
        script = Path(script_path)
        source = script.read_text(encoding="utf-8-sig")
        try:
            tree = ast.parse(source, filename=str(script))
        except SyntaxError as exc:
            raise DependencyError(
                f"Python-filen har en syntaxfejl på linje {exc.lineno}: {exc.msg}"
            ) from exc

        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    imports.add(node.module.split(".", 1)[0])

        return sorted(imports, key=str.lower)

    def _is_local_module(self, module: str, script_path: Path) -> bool:
        folder = script_path.parent
        return (folder / f"{module}.py").exists() or (folder / module / "__init__.py").exists()

    def external_imports(self, script_path: str | Path) -> list[str]:
        script = Path(script_path).resolve()
        found = self.parse_imports(script)

        stdlib = getattr(sys, "stdlib_module_names", set())
        result: list[str] = []
        for module in found:
            if module in stdlib:
                continue
            if module == "__future__":
                continue
            if self._is_local_module(module, script):
                continue
            result.append(module)
        return result

    def package_for_import(self, module: str) -> str:
        return IMPORT_TO_PACKAGE.get(module, module)

    def cache_file_for_env(self, env_dir: Path) -> Path:
        return env_dir / ".installed_libs.json"

    def site_packages_dirs(self, env_dir: Path) -> list[Path]:
        if IS_WINDOWS:
            candidate = env_dir / "Lib" / "site-packages"
            return [candidate] if candidate.is_dir() else []

        lib_dir = env_dir / "lib"
        if not lib_dir.is_dir():
            return []

        return [
            path
            for path in sorted(lib_dir.glob("python*/site-packages"))
            if path.is_dir()
        ]

    @staticmethod
    def _normalize_package_name(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()

    def _environment_stamp(self, env_dir: Path) -> float:
        stamps: list[float] = []
        for site_packages in self.site_packages_dirs(env_dir):
            try:
                stamps.append(site_packages.stat().st_mtime)
            except OSError:
                pass

            for metadata_dir in site_packages.glob("*.dist-info"):
                try:
                    stamps.append(metadata_dir.stat().st_mtime)
                except OSError:
                    pass

        return max(stamps, default=0.0)

    def build_library_cache(
        self,
        env_dir: Path,
        log: Callable[[str], None] | None = None,
    ) -> dict:
        modules: set[str] = set()
        packages: dict[str, str] = {}

        for site_packages in self.site_packages_dirs(env_dir):
            try:
                entries = list(site_packages.iterdir())
            except OSError:
                continue

            for entry in entries:
                name = entry.name

                if name.endswith(".py") and name != "__init__.py":
                    modules.add(entry.stem)
                elif entry.is_dir() and not name.endswith((".dist-info", ".data")):
                    if (entry / "__init__.py").exists() or not name.startswith("."):
                        modules.add(name)

            for dist_info in site_packages.glob("*.dist-info"):
                metadata_file = dist_info / "METADATA"
                package_name = ""
                package_version = ""

                if metadata_file.is_file():
                    try:
                        for line in metadata_file.read_text(
                            encoding="utf-8",
                            errors="replace",
                        ).splitlines():
                            if line.startswith("Name: ") and not package_name:
                                package_name = line[6:].strip()
                            elif line.startswith("Version: ") and not package_version:
                                package_version = line[9:].strip()

                            if package_name and package_version:
                                break
                    except OSError:
                        pass

                if package_name:
                    packages[self._normalize_package_name(package_name)] = package_version

                top_level = dist_info / "top_level.txt"
                if top_level.is_file():
                    try:
                        for line in top_level.read_text(
                            encoding="utf-8",
                            errors="replace",
                        ).splitlines():
                            module = line.strip()
                            if module and module.isidentifier():
                                modules.add(module)
                    except OSError:
                        pass

        cache = {
            "version": 1,
            "environment": str(env_dir.resolve()),
            "environment_stamp": self._environment_stamp(env_dir),
            "modules": sorted(modules, key=str.lower),
            "packages": dict(sorted(packages.items())),
        }

        cache_file = self.cache_file_for_env(env_dir)
        try:
            cache_file.write_text(
                json.dumps(cache, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

        if log:
            log(
                f"Library cache updated: {len(cache['modules'])} import names, "
                f"{len(cache['packages'])} packages."
            )

        return cache

    def load_library_cache(
        self,
        env_dir: Path,
        log: Callable[[str], None] | None = None,
    ) -> dict:
        cache_file = self.cache_file_for_env(env_dir)

        if cache_file.is_file():
            try:
                cache = json.loads(cache_file.read_text(encoding="utf-8"))
                cached_stamp = float(cache.get("environment_stamp", -1))
                current_stamp = self._environment_stamp(env_dir)

                if (
                    cache.get("version") == 1
                    and cache.get("environment") == str(env_dir.resolve())
                    and cached_stamp >= current_stamp
                ):
                    return cache
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass

        if log:
            log("Building installed-library cache...")

        return self.build_library_cache(env_dir, log)

    def module_available(
        self,
        env_dir: Path,
        module: str,
        cache: dict | None = None,
    ) -> bool:
        cache = cache or self.load_library_cache(env_dir)
        modules = set(cache.get("modules", []))

        if module in modules:
            return True

        package = self._normalize_package_name(self.package_for_import(module))
        installed_packages = cache.get("packages", {})
        return package in installed_packages

    def install_dependencies(
        self,
        script_path: str | Path,
        log: Callable[[str], None],
    ) -> tuple[Path, list[str], list[str]]:
        script = Path(script_path).resolve()
        env_dir = self.ensure_env(script, log)

        imports = self.external_imports(script)
        if not imports:
            log("Ingen eksterne imports fundet.")
            return env_dir, [], []

        log("Fundne eksterne imports: " + ", ".join(imports))
        library_cache = self.load_library_cache(env_dir, log)
        missing = [
            module
            for module in imports
            if not self.module_available(env_dir, module, library_cache)
        ]

        if not missing:
            log("Alle nødvendige biblioteker er allerede installeret.")
            return env_dir, imports, []

        packages: list[str] = []
        seen: set[str] = set()
        for module in missing:
            package = self.package_for_import(module)
            if package.lower() not in seen:
                seen.add(package.lower())
                packages.append(package)

        log("Installerer manglende pakker: " + ", ".join(packages))
        command = self.pip_for_env(env_dir) + [
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            *packages,
        ]

        result = subprocess.Popen(
            command,
            cwd=str(script.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
        )
        assert result.stdout is not None
        for line in result.stdout:
            log(line.rstrip())
        code = result.wait()

        if code != 0:
            raise DependencyError(
                "pip kunne ikke installere alle dependencies. "
                "Se loggen ovenfor. Nogle importnavne matcher ikke navnet på PyPI-pakken."
            )

        library_cache = self.build_library_cache(env_dir, log)
        still_missing = [
            module
            for module in missing
            if not self.module_available(env_dir, module, library_cache)
        ]
        if still_missing:
            raise DependencyError(
                "Disse imports kan stadig ikke findes efter installation: "
                + ", ".join(still_missing)
            )

        log("Dependencies er klar.")
        return env_dir, imports, packages

    def start_script(
        self,
        script_path: str | Path,
        window: WindowInfo | None,
        log: Callable[[str], None],
        on_exit: Callable[[int], None],
        on_input: Callable[[str], str | None] | None = None,
        arguments: list[str] | None = None,
        expected_script_hash: str | None = None,
    ) -> None:
        script = Path(script_path).resolve()
        if not script.exists():
            raise FileNotFoundError(script)

        with self._lock:
            if self.process and self.process.poll() is None:
                raise RuntimeError("Der kører allerede et script.")

        if expected_script_hash:
            self.verify_script_integrity(
                script,
                expected_script_hash,
                "before dependency preparation",
                log,
            )

        env_dir, _, _ = self.install_dependencies(script, log)

        if expected_script_hash:
            self.verify_script_integrity(
                script,
                expected_script_hash,
                "after dependency preparation",
                log,
            )

        python_exe = self.python_for_env(env_dir)

        child_env = os.environ.copy()
        child_env["PYTHONUNBUFFERED"] = "1"
        child_env["PYTHONUTF8"] = "1"
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PY_EXECUTOR_SCRIPT"] = str(script)
        child_env["PY_EXECUTOR_ENV"] = str(env_dir)

        if window:
            child_env["PY_EXECUTOR_WINDOW_HANDLE"] = str(window.hwnd)
            child_env["PY_EXECUTOR_WINDOW_TITLE"] = window.title
            child_env["PY_EXECUTOR_WINDOW_PID"] = str(window.pid)
            child_env["PY_EXECUTOR_WINDOW_PROCESS"] = window.process_name
            focus_window(window.hwnd)
        else:
            child_env.pop("PY_EXECUTOR_WINDOW_HANDLE", None)
            child_env.pop("PY_EXECUTOR_WINDOW_TITLE", None)
            child_env.pop("PY_EXECUTOR_WINDOW_PID", None)
            child_env.pop("PY_EXECUTOR_WINDOW_PROCESS", None)

        log(f"Starter: {script.name}")
        if window:
            log(f"Valgt vindue: {window.display_name}")

        if expected_script_hash:
            self.verify_script_integrity(
                script,
                expected_script_hash,
                "immediately before process start",
                log,
            )

        process = subprocess.Popen(
            [
                str(python_exe),
                "-u",
                str(Path(__file__).resolve()),
                "--input-bridge",
                str(script),
                *(arguments or []),
            ],
            cwd=str(script.parent),
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
        )

        with self._lock:
            self.process = process

        if expected_script_hash:
            self.verify_script_integrity(
                script,
                expected_script_hash,
                "immediately after process start",
                log,
            )

        def pump() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                clean = line.rstrip("\r\n")

                if clean.startswith("__PYEXEC_INPUT__:"):
                    prompt = ""
                    try:
                        prompt = json.loads(clean.split(":", 1)[1])
                    except (json.JSONDecodeError, TypeError):
                        prompt = clean.split(":", 1)[1]

                    response = on_input(prompt) if on_input else ""
                    if response is None:
                        response = ""

                    if process.stdin:
                        try:
                            process.stdin.write(str(response) + "\n")
                            process.stdin.flush()
                        except (BrokenPipeError, OSError):
                            pass
                    continue

                log(clean)
            code = process.wait()

            if expected_script_hash:
                try:
                    self.verify_script_integrity(
                        script,
                        expected_script_hash,
                        "after script execution",
                        log,
                    )
                except ScriptIntegrityError as exc:
                    log(str(exc))

            log(f"Script afsluttet med exit code {code}.")
            with self._lock:
                if self.process is process:
                    self.process = None
            on_exit(code)

        threading.Thread(target=pump, daemon=True).start()

    def stop_script(self, log: Callable[[str], None]) -> bool:
        with self._lock:
            process = self.process

        if not process or process.poll() is not None:
            return False

        log("Stopper script...")
        try:
            if IS_WINDOWS:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                process.terminate()
        finally:
            with self._lock:
                self.process = None
        return True

    def reset_env(self, script_path: str | Path) -> Path:
        env_dir = self.env_dir_for_script(script_path)
        if env_dir.exists():
            shutil.rmtree(env_dir)
        return env_dir


def enumerate_windows() -> list[WindowInfo]:
    if not IS_WINDOWS:
        return []

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    windows: list[WindowInfo] = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def process_name_for_pid(pid: int) -> str:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return Path(buffer.value).name
        finally:
            kernel32.CloseHandle(handle)
        return ""

    @EnumWindowsProc
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        title_buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, length + 1)
        title = title_buffer.value.strip()
        if not title:
            return True

        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, 256)

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        windows.append(
            WindowInfo(
                hwnd=int(hwnd),
                title=title,
                class_name=class_buffer.value,
                pid=int(pid.value),
                process_name=process_name_for_pid(int(pid.value)),
            )
        )
        return True

    user32.EnumWindows(callback, 0)
    windows.sort(key=lambda item: (item.process_name.lower(), item.title.lower()))
    return windows


def focus_window(hwnd: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False

    user32 = ctypes.windll.user32
    SW_RESTORE = 9
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:
        return False


@dataclass(frozen=True)
class ArgumentSpec:
    position: int
    name: str


class _ArgumentVisitor(ast.NodeVisitor):
    def __init__(self):
        self.argparse: list[str] = []

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                name = first.value
                if not name.startswith("-"):
                    nargs = None
                    for kw in node.keywords:
                        if kw.arg == "nargs" and isinstance(kw.value, ast.Constant):
                            nargs = kw.value.value

                    if nargs not in {"?", "*"}:
                        self.argparse.append(name)

        self.generic_visit(node)


def detect_required_arguments(script_path: str | Path) -> list[ArgumentSpec]:
    path = Path(script_path)
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(path))

    visitor = _ArgumentVisitor()
    visitor.visit(tree)

    return [
        ArgumentSpec(position, name)
        for position, name in enumerate(visitor.argparse, start=1)
    ]


def _nested_argv_index(node: ast.AST) -> int | None:
    if isinstance(node, ast.Subscript):
        value = node.value
        if (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id == "sys"
            and value.attr == "argv"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, int)
        ):
            return node.slice.value

    if isinstance(node, ast.Call):
        index = _nested_argv_index(node.func)
        if index is not None:
            return index
        for arg in node.args:
            index = _nested_argv_index(arg)
            if index is not None:
                return index

    if isinstance(node, ast.Attribute):
        return _nested_argv_index(node.value)

    return None


class _OptionalArgVisitor(ast.NodeVisitor):
    def __init__(self):
        self.handles_argv_length = False
        self.first_arg_name = ""

    def visit_Call(self, node: ast.Call):
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "len"
            and node.args
            and isinstance(node.args[0], ast.Attribute)
            and isinstance(node.args[0].value, ast.Name)
            and node.args[0].value.id == "sys"
            and node.args[0].attr == "argv"
        ):
            self.handles_argv_length = True
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        if _nested_argv_index(node.value) == 1 and node.targets:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                self.first_arg_name = target.id
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if node.value is not None and _nested_argv_index(node.value) == 1:
            if isinstance(node.target, ast.Name):
                self.first_arg_name = node.target.id
        self.generic_visit(node)


def detect_optional_first_argument(script_path: str | Path) -> str | None:
    path = Path(script_path)
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(path))

    visitor = _OptionalArgVisitor()
    visitor.visit(tree)

    if visitor.handles_argv_length and visitor.first_arg_name:
        return visitor.first_arg_name

    return None


@dataclass(frozen=True)
class ScriptChoice:
    value: str
    label: str


def _resolve_script_path_expression(node: ast.AST, script_path: Path) -> Path | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _resolve_script_path_expression(node.left, script_path)
        if left is None:
            return None
        if isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
            return left / node.right.value
        return None

    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = _resolve_script_path_expression(node.value, script_path)
        return base.parent if base is not None else None

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "Path" and len(node.args) == 1:
            arg = node.args[0]
            if isinstance(arg, ast.Name) and arg.id == "__file__":
                return script_path.resolve()
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                value = Path(arg.value)
                if value.is_absolute():
                    return value
                return (script_path.parent / value).resolve()

        if isinstance(node.func, ast.Attribute) and node.func.attr == "joinpath":
            base = _resolve_script_path_expression(node.func.value, script_path)
            if base is None:
                return None
            parts = []
            for arg in node.args:
                if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                    return None
                parts.append(arg.value)
            return base.joinpath(*parts)

    return None


def detect_song_directory(script_path: str | Path) -> Path | None:
    path = Path(script_path).resolve()
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(path))

    candidates: list[tuple[int, Path]] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue

        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if value is None:
            continue

        for target in targets:
            if not isinstance(target, ast.Name):
                continue

            resolved = _resolve_script_path_expression(value, path)
            if resolved is None:
                continue

            name = target.id.lower()
            score = 0
            if "song" in name:
                score += 10
            if name.endswith("_dir") or name.endswith("_folder"):
                score += 4
            if resolved.name.lower() in {"songs", "song", "music"}:
                score += 6

            if score:
                candidates.append((score, resolved))

    ranked = sorted(candidates, key=lambda item: item[0], reverse=True)

    for _, candidate in ranked:
        if candidate.is_dir():
            return candidate

    if ranked:
        return ranked[0][1]

    return None


def detect_song_choices(script_path: str | Path) -> tuple[Path | None, list[ScriptChoice]]:
    songs_dir = detect_song_directory(script_path)
    if songs_dir is None:
        return None, []

    ids: set[str] = set()

    for file in songs_dir.glob("*.json"):
        if not file.name.endswith(".meta.json"):
            ids.add(file.stem)

    for file in songs_dir.glob("*.txt"):
        ids.add(file.stem)

    choices: list[ScriptChoice] = []

    for song_id in sorted(ids, key=str.lower):
        display_name = song_id
        json_path = songs_dir / f"{song_id}.json"
        meta_path = songs_dir / f"{song_id}.meta.json"

        data = None
        source_file = json_path if json_path.is_file() else meta_path
        if source_file.is_file():
            try:
                data = json.loads(source_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeError):
                data = None

        if isinstance(data, dict):
            name = str(data.get("name", "")).strip()
            if name:
                display_name = name

        label = display_name
        if display_name.casefold() != song_id.casefold():
            label = f"{display_name}: {song_id}"

        choices.append(ScriptChoice(song_id, label))

    return songs_dir, choices


@dataclass(frozen=True)
class SecurityFinding:
    severity: str
    file: str
    line: int
    title: str
    detail: str

    def display(self) -> str:
        location = f"{self.file}:{self.line}" if self.line else self.file
        return f"[{self.severity.upper()}] {location} - {self.title}\n{self.detail}"


NETWORK_MODULES = {
    "socket", "requests", "urllib", "httpx", "aiohttp", "ftplib",
    "paramiko", "websockets", "websocket",
}
PROCESS_MODULES = {"subprocess", "pty"}
KEYLOG_MODULES = {"keyboard", "pynput", "pyHook", "pythoncom"}
CREDENTIAL_TERMS = {
    "password", "passwd", "token", "cookie", "cookies", "credential",
    "credentials", "discord_token", "browser_password", "login_data",
}
PERSISTENCE_TERMS = {
    "currentversion\\run", "currentversion/run", "startup",
    "schtasks", "task scheduler", "startupapproved",
}
SHELL_TERMS = {
    "powershell", "cmd.exe", "/bin/sh", "/bin/bash", "encodedcommand",
    "-enc ", "shell=true",
}


class _Analyzer(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.imports: set[str] = set()
        self.calls: list[tuple[str, int, str]] = []
        self.strings: list[tuple[str, int]] = []
        self.has_exec = False
        self.has_eval = False
        self.has_base64_decode = False
        self.has_network = False
        self.has_process = False
        self.has_keylog = False
        self.has_os_system = False
        self.has_registry = False

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            self.imports.add(root)
            self._mark_import(root)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            root = node.module.split(".", 1)[0]
            self.imports.add(root)
            self._mark_import(root)
        self.generic_visit(node)

    def _mark_import(self, root: str):
        if root in NETWORK_MODULES:
            self.has_network = True
        if root in PROCESS_MODULES:
            self.has_process = True
        if root in KEYLOG_MODULES:
            self.has_keylog = True
        if root in {"winreg"}:
            self.has_registry = True

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str):
            self.strings.append((node.value, getattr(node, "lineno", 0)))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        name = self._call_name(node.func)
        line = getattr(node, "lineno", 0)
        source = ""

        try:
            source = ast.unparse(node)
        except Exception:
            pass

        lowered = name.lower()
        self.calls.append((lowered, line, source))

        if lowered in {"exec", "builtins.exec"}:
            self.has_exec = True
        elif lowered in {"eval", "builtins.eval"}:
            self.has_eval = True
        elif lowered.endswith("b64decode") or lowered.endswith("urlsafe_b64decode"):
            self.has_base64_decode = True
        elif lowered in {"os.system", "system"}:
            self.has_os_system = True
            self.has_process = True
        elif lowered.startswith("subprocess."):
            self.has_process = True
        elif lowered.startswith(("requests.", "urllib.", "httpx.", "aiohttp.")):
            self.has_network = True
        elif lowered.startswith(("socket.", "socket")):
            self.has_network = True
        elif lowered.startswith("winreg."):
            self.has_registry = True

        self.generic_visit(node)

    @staticmethod
    def _call_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parts = []
            current: ast.AST | None = node
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        return ""


def _local_imports(path: Path, imports: set[str]) -> list[Path]:
    result: list[Path] = []
    folder = path.parent

    for module in imports:
        py_file = folder / f"{module}.py"
        package_init = folder / module / "__init__.py"

        if py_file.is_file():
            result.append(py_file.resolve())
        elif package_init.is_file():
            result.append(package_init.resolve())

    return result


def _first_matching_string(analyzer: _Analyzer, terms: set[str]) -> tuple[str, int] | None:
    for value, line in analyzer.strings:
        lower = value.lower()
        if any(term in lower for term in terms):
            return value, line
    return None


def _analyze_file(path: Path) -> tuple[list[SecurityFinding], set[str]]:
    findings: list[SecurityFinding] = []

    try:
        source = path.read_text(encoding="utf-8-sig", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return findings, set()

    analyzer = _Analyzer(path)
    analyzer.visit(tree)

    file_name = path.name

    if analyzer.has_base64_decode and (analyzer.has_exec or analyzer.has_eval):
        line = next(
            (line for name, line, _ in analyzer.calls if name in {"exec", "eval", "builtins.exec", "builtins.eval"}),
            0,
        )
        findings.append(SecurityFinding(
            "high", file_name, line,
            "Obfuscated code execution",
            "The script decodes Base64 data and executes/evaluates code dynamically.",
        ))

    if analyzer.has_network and (analyzer.has_exec or analyzer.has_eval):
        line = next(
            (line for name, line, _ in analyzer.calls if name in {"exec", "eval", "builtins.exec", "builtins.eval"}),
            0,
        )
        findings.append(SecurityFinding(
            "high", file_name, line,
            "Network content combined with dynamic code execution",
            "The script uses networking together with exec/eval, which can be used to download and run remote code.",
        ))

    shell_match = _first_matching_string(analyzer, SHELL_TERMS)
    if analyzer.has_network and analyzer.has_process and shell_match:
        _, line = shell_match
        findings.append(SecurityFinding(
            "high", file_name, line,
            "Possible remote shell/backdoor",
            "Networking is combined with process execution and shell-related commands.",
        ))

    if analyzer.has_keylog and analyzer.has_network:
        findings.append(SecurityFinding(
            "high", file_name, 0,
            "Possible keylogger with network access",
            "Keyboard capture libraries and networking are both used in this file.",
        ))

    persistence = _first_matching_string(analyzer, PERSISTENCE_TERMS)
    if persistence and (analyzer.has_registry or analyzer.has_process or analyzer.has_os_system):
        _, line = persistence
        findings.append(SecurityFinding(
            "high", file_name, line,
            "Possible persistence mechanism",
            "The script appears to modify startup/Run keys or scheduled tasks so code can start automatically.",
        ))

    credential = _first_matching_string(analyzer, CREDENTIAL_TERMS)
    if credential and analyzer.has_network:
        _, line = credential
        findings.append(SecurityFinding(
            "medium", file_name, line,
            "Possible credential/token exfiltration",
            "Credential-, token-, cookie-, or password-related data appears together with network access.",
        ))

    for name, line, call_source in analyzer.calls:
        lower = call_source.lower()
        if (
            name.startswith("subprocess.")
            or name == "os.system"
        ) and ("encodedcommand" in lower or re.search(r"\bpowershell(?:\.exe)?\b.*\s-(?:enc|encodedcommand)\b", lower)):
            findings.append(SecurityFinding(
                "high", file_name, line,
                "Encoded PowerShell execution",
                "The script launches an encoded PowerShell command, a technique commonly used to hide payloads.",
            ))
            break

    if (analyzer.has_exec or analyzer.has_eval) and not any(
        f.title.startswith(("Obfuscated", "Network content")) for f in findings
    ):
        line = next(
            (line for name, line, _ in analyzer.calls if name in {"exec", "eval", "builtins.exec", "builtins.eval"}),
            0,
        )
        findings.append(SecurityFinding(
            "medium", file_name, line,
            "Dynamic code execution",
            "The script uses exec/eval. This can be legitimate, but it can also hide code that is only constructed at runtime.",
        ))

    return findings, analyzer.imports


def scan_script(script_path: str | Path, max_files: int = 100) -> list[SecurityFinding]:
    root = Path(script_path).resolve()
    queue: list[Path] = [root]
    visited: set[Path] = set()
    findings: list[SecurityFinding] = []

    while queue and len(visited) < max_files:
        path = queue.pop(0)
        if path in visited or not path.is_file() or path.suffix.lower() != ".py":
            continue

        visited.add(path)
        file_findings, imports = _analyze_file(path)
        findings.extend(file_findings)

        for local_file in _local_imports(path, imports):
            if local_file not in visited:
                queue.append(local_file)

    unique: list[SecurityFinding] = []
    seen: set[tuple[str, str, int, str]] = set()
    for finding in findings:
        key = (finding.severity, finding.file, finding.line, finding.title)
        if key not in seen:
            seen.add(key)
            unique.append(finding)

    return unique

TECHNICAL = re.compile(
    r"(^\s*$|^\s*File [\"']|^\s*Traceback \(|^\s*\^+\s*$|"
    r"^\s*(?:FileNotFoundError|ModuleNotFoundError|ImportError|SyntaxError|"
    r"TypeError|ValueError|AttributeError|KeyError|RuntimeError|OSError):|"
    r"^\s*\[\d{4}-\d\d-\d\d|^\s*[{\[]|"
    r"https?://|[A-Za-z]:\\|/(?:home|usr|mnt|opt|var)/|"
    r"^\s*(?:pip |python |>>> |\$ |# )|"
    r"^\s*\w+\s*=\s*\S+)",
    re.IGNORECASE,
)


class LogTranslator:
    def __init__(self, deliver: Callable[[str], None]):
        self.deliver = deliver
        self.tasks: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self.cache: OrderedDict[tuple[str, str], str] = OrderedDict()
        self.worker = threading.Thread(target=self._work, name="LogTranslator", daemon=True)
        self.worker.start()

    def submit(self, text: str, language: str) -> None:
        self.tasks.put((text, language if language in ("en", "da") else "en"))

    def _translate(self, text: str, language: str) -> str:
        if len(text) > 1500 or TECHNICAL.search(text) or not any(c.isalpha() for c in text):
            return text

        key = (language, text)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]

        params = urllib.parse.urlencode({
            "client": "gtx", "sl": "auto", "tl": language,
            "dt": "t", "q": text,
        })
        url = "https://translate.googleapis.com/translate_a/single?" + params
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PythonExecutor/1.0)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=3.0) as response:
                data = json.load(response)
            translated = "".join(
                piece[0] for piece in data[0]
                if isinstance(piece, list) and piece and isinstance(piece[0], str)
            ).strip()
            result = translated or text
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            result = text

        self.cache[key] = result
        if len(self.cache) > 500:
            self.cache.popitem(last=False)
        return result

    def _work(self) -> None:
        while True:
            item = self.tasks.get()
            if item is None:
                self.tasks.task_done()
                break
            text, language = item
            try:
                self.deliver(self._translate(text, language))
            except Exception:
                pass
            finally:
                self.tasks.task_done()

    def close(self) -> None:
        self.tasks.put(None)


def _run_input_bridge() -> None:
    prefix = "__PYEXEC_INPUT__:"

    def executor_input(prompt=""):
        sys.stdout.write(prefix + json.dumps(str(prompt), ensure_ascii=False) + "\n")
        sys.stdout.flush()
        value = sys.stdin.readline()
        if value == "":
            raise EOFError
        return value.rstrip("\r\n")

    builtins.input = executor_input
    script = str(Path(sys.argv[2]).resolve())
    sys.path.insert(0, str(Path(script).parent))
    sys.argv = [script, *sys.argv[3:]]
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__" and len(sys.argv) >= 3 and sys.argv[1] == "--input-bridge":
    _run_input_bridge()
