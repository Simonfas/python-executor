# Python Executor

Python Executor is a Windows desktop application for running Python scripts without opening VS Code or another IDE.

It can automatically prepare dependencies, reuse installed libraries across scripts, focus a selected Windows window, translate log output, scan scripts for suspicious behavior, and stop a running script with a global keyboard shortcut.

## Features

- Run any local `.py` file.
- Select an open Windows window before starting a script.
- Automatically focus the selected window.
- Pass window information to the script through environment variables.
- Scan imports with Python AST before execution.
- Ignore standard-library imports and local modules.
- Use one shared virtual environment for all scripts.
- Reuse installed libraries across different scripts.
- Automatically install missing PyPI packages.
- Cache installed libraries locally to avoid unnecessary checks.
- Check pip for updates automatically.
- Update installed libraries when pip itself is updated.
- Check the latest official Python version during startup.
- Translate human-readable log output to the selected UI language.
- English and Danish interface, with the selected language saved between sessions.
- Scan scripts and local imported Python files for suspicious backdoor or malware patterns.
- Ask for confirmation before running a script when suspicious behavior is detected.
- Stop a running script globally with **Ctrl+C**, even when another window has focus.
- View stdout and stderr live inside the application.
- Stop scripts directly from the interface.
- Uninstall the Python installation used by the executor from the interface.

## Requirements

Python Executor is designed for **Windows**.

Start it by double-clicking:

```bat
run.bat
```

The launcher checks for Python before starting the application. If Python is missing or outdated, it attempts to install the latest official Python release automatically.

You can also start the application manually with:

```powershell
py -3 app.py
```

The application itself uses only Python's standard library.

## Shared Python Environment

All executed scripts use the same executor-managed virtual environment:

```text
.executor_envs/shared/
```

This means a library only needs to be installed once.

For example:

```text
Script A requires requests
→ requests is installed in shared

Script B requires requests
→ requests is already available
→ nothing is installed

Script C requires requests and Pillow
→ requests is reused
→ only Pillow is installed
```

Installed package information is cached in:

```text
.executor_envs/shared/.installed_libs.json
```

The cache is refreshed when the environment changes or new packages are installed.

## Dependency Detection

Before a script starts, Python Executor parses its imports using Python's `ast` module.

Example:

```python
import requests
import cv2
from PIL import Image
```

The executor resolves those imports to packages such as:

```text
requests
opencv-python
Pillow
```

Some Python import names do not match their PyPI package names. Known mappings are handled automatically, including examples such as:

| Import | PyPI package |
| --- | --- |
| `PIL` | `Pillow` |
| `cv2` | `opencv-python` |
| `sklearn` | `scikit-learn` |
| `yaml` | `PyYAML` |
| `win32gui` | `pywin32` |
| `dotenv` | `python-dotenv` |

Additional mappings can be added to `IMPORT_TO_PACKAGE` in `executor_core.py`.

## pip and Library Updates

Python Executor checks pip when preparing the shared environment.

If a newer pip version is installed, the executor also checks installed libraries for available updates and upgrades them where possible.

Package installation uses `--no-cache-dir` to avoid permission problems caused by the global Windows pip cache.

## Security Scan

Every script is scanned before execution.

The scanner also follows local Python imports and checks related `.py` files.

It looks for suspicious combinations such as:

- network access combined with `exec` or `eval`
- Base64 decoding combined with dynamic code execution
- socket communication combined with shell or process execution
- keylogging libraries combined with network access
- startup persistence or scheduled-task behavior
- credential, token, cookie, or password access combined with network communication
- encoded PowerShell execution

The scan is heuristic and can produce false positives.

If suspicious behavior is found, Python Executor shows the findings and asks whether the script should still be started.

It does **not** guarantee that a script is safe.

## Command-line Arguments

Before a script starts, Python Executor checks for required positional command-line arguments.

It supports common patterns such as:

```python
song_id = sys.argv[1]
```

and positional arguments created with `argparse`.

If a required argument is detected, the executor opens a popup before launching the script. For example, `song_id = sys.argv[1]` produces an **Enter song id** prompt.

The entered values are passed to the script through `sys.argv` exactly like normal command-line arguments. Cancelling a required argument prompt cancels the script launch.

## Script Input Dialogs

When a running script calls Python's built-in `input()`, Python Executor automatically opens a text dialog.

For example:

```python
bpm = input("Enter BPM: ")
```

Instead of waiting for input in a terminal, the executor displays **Enter BPM:** in a popup. The entered value is sent back to the script as the return value from `input()`.

Cancelling the dialog sends an empty string.

## Global Ctrl+C Stop

While a script is running, pressing:

```text
Ctrl + C
```

stops the script even when another application has focus.

The shortcut is monitored globally without registering Ctrl+C as an exclusive Windows hotkey, so normal copy behavior in other applications is not intentionally blocked.

## Selected Windows Window

When a window is selected, Python Executor attempts to focus it before the script starts.

Information about the selected window is also passed to the script through environment variables:

```text
PY_EXECUTOR_WINDOW_HANDLE
PY_EXECUTOR_WINDOW_TITLE
PY_EXECUTOR_WINDOW_PID
PY_EXECUTOR_WINDOW_PROCESS
PY_EXECUTOR_SCRIPT
PY_EXECUTOR_ENV
```

Example:

```python
import os

hwnd = int(os.getenv("PY_EXECUTOR_WINDOW_HANDLE", "0"))
title = os.getenv("PY_EXECUTOR_WINDOW_TITLE", "")

print(hwnd, title)
```

## Log Translation

The interface supports:

- English
- Danish

English is the default language.

The selected language is saved locally and restored the next time the application starts.

Human-readable log output can be translated automatically to the selected language. Technical output such as tracebacks, paths, JSON, and pip progress is generally kept unchanged to make debugging easier.

Translation is best-effort and requires internet access. If translation fails, the original log line is shown.

## Project Files

```text
app.py
executor_core.py
run.bat
README.md
uninstall/
  uninstall_python.bat
  uninstall_python.ps1
```

### `app.py`

Main graphical interface and application flow.

### `executor_core.py`

Contains the executor engine, dependency handling, shared environment management, pip updates, library cache, Windows window handling, security scanning, command-line argument detection, log translation, and the runtime input bridge.

### `run.bat`

Windows launcher, Python version check, Python installation flow, and initial pip update.

### `uninstall/`

Contains the uninstall helpers used by the **Uninstall Python** button. They are kept outside the project root to reduce the chance of launching them accidentally.

## Important Notes

Python scripts run with the same Windows permissions as Python Executor.

Automatically installed packages come from PyPI through pip.

Only run scripts you trust, especially scripts downloaded from unknown sources. The built-in security scanner can identify some suspicious patterns, but it is not a replacement for antivirus software, sandboxing, or manual code review.
