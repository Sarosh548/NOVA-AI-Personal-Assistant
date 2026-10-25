from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus, urlsplit


class DesktopControlService:
    """Bounded, opt-in Windows desktop controls; never executes arbitrary commands."""

    FOLDER_NAMES = {
        "desktop": "Desktop",
        "documents": "Documents",
        "downloads": "Downloads",
        "pictures": "Pictures",
        "music": "Music",
        "videos": "Videos",
    }
    # Fixed drive roots are a small, explicit allowlist; callers cannot supply paths.
    DRIVE_ROOTS = {
        "local disk c": Path("C:/"),
        "local drive c": Path("C:/"),
        "disk c": Path("C:/"),
        "c drive": Path("C:/"),
        "drive c": Path("C:/"),
    }
    SAFE_OPEN_EXTENSIONS = {
        ".pdf", ".doc", ".docx", ".rtf", ".txt", ".md", ".csv",
        ".xls", ".xlsx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg",
        ".gif", ".webp", ".bmp", ".mp3", ".wav", ".m4a", ".mp4",
        ".mov", ".avi", ".mkv",
    }
    SKIP_DIRECTORIES = {
        ".git", ".venv", "venv", "node_modules", "__pycache__",
        "appdata", "windows", "program files", "program files (x86)",
        # Do not spend a profile-wide document search on developer/runtime packages.
        "anaconda3", "miniconda3", "miniforge3", ".conda", ".cache",
        ".npm", ".cargo", ".rustup", ".gradle", ".m2", "site-packages",
    }
    CV_SEARCH_EXTENSIONS = {".pdf", ".doc", ".docx", ".rtf", ".odt", ".txt", ".pages"}
    CV_FILENAME_PATTERN = re.compile(
        r"(?<![a-z0-9])cv(?![a-z0-9])"
        r"|(?<![a-z0-9])resume(?:s)?(?![a-z0-9])"
        r"|(?<![a-z0-9])curriculum[\s._-]+vitae(?![a-z0-9])",
        re.IGNORECASE,
    )
    MAX_SEARCHED_FILES = 6000
    MAX_RESULTS = 15

    APP_ALIASES = {
        "calculator": "calculator",
        "calc": "calculator",
        "notepad": "notepad",
        "text editor": "notepad",
        "file explorer": "explorer",
        "explorer": "explorer",
        "edge": "edge",
        "microsoft edge": "edge",
        "chrome": "chrome",
        "google chrome": "chrome",
        "firefox": "firefox",
        "outlook": "outlook",
        "microsoft outlook": "outlook",
        "word": "word",
        "microsoft word": "word",
        "excel": "excel",
        "microsoft excel": "excel",
        "powerpoint": "powerpoint",
        "microsoft powerpoint": "powerpoint",
        "spotify": "spotify",
        "microsoft store": "microsoft_store",
        "store": "microsoft_store",
    }

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        platform_name: str | None = None,
        environment: str | None = None,
        home_directory: Path | str | None = None,
        process_launcher: Callable[[list[str]], object] | None = None,
        url_opener: Callable[[str], bool] | None = None,
        file_opener: Callable[[str], object] | None = None,
    ) -> None:
        self.platform_name = platform_name if platform_name is not None else os.name
        self.environment = (
            str(environment).strip().lower()
            if environment is not None
            else os.getenv("NOVA_ENV", "development").strip().lower()
        )
        if enabled is None:
            enabled = os.getenv("NOVA_DESKTOP_CONTROL_ENABLED", "").strip().lower() in {
                "1", "true", "yes", "on",
            }
        self.enabled = bool(enabled)
        self.home_directory = Path(home_directory) if home_directory is not None else Path.home()
        self._process_launcher = process_launcher or self._launch_process
        self._url_opener = url_opener or webbrowser.open_new_tab
        self._file_opener = file_opener or self._open_with_default_application

    @property
    def is_available(self) -> bool:
        """Opt-in local desktop execution; never expose it from production."""
        return (
            self.enabled
            and self.platform_name == "nt"
            and self.environment == "development"
        )

    @staticmethod
    def _launch_process(command: list[str]) -> object:
        return subprocess.Popen(command, shell=False, close_fds=True)

    def _open_with_default_application(self, path: str) -> object:
        if self.platform_name != "nt" or not hasattr(os, "startfile"):
            raise OSError("Opening local files is supported only on Windows.")
        return os.startfile(path)  # type: ignore[attr-defined]

    @staticmethod
    def _failed(action: str, message: str, *, result: dict | None = None) -> dict:
        return {
            "success": False,
            "tool": "desktop",
            "action": action,
            "result": result,
            "error": message,
        }

    @staticmethod
    def _succeed(action: str, title: str, **details: object) -> dict:
        return {
            "success": True,
            "tool": "desktop",
            "action": action,
            "result": {"title": title, **details},
            "error": None,
        }

    def execute(self, *, user_id: str, action: str, data: dict) -> dict:
        # user_id is deliberately accepted to match NOVA's ToolRouter contract.
        # Device control is available only to the authenticated local app process.
        del user_id
        normalized_action = str(action or "").strip().lower()
        if not self.is_available:
            return self._failed(
                normalized_action,
                "Local desktop control is disabled. Enable NOVA_DESKTOP_CONTROL_ENABLED=true "
                "for a trusted Windows desktop development session.",
            )

        operation = str(data.get("desktop_operation") or "").strip().lower()
        if normalized_action == "search" and operation == "find_files":
            return self._find_files(data.get("desktop_query") or data.get("query"))
        if normalized_action == "search" and operation == "list_files":
            return self._list_files(data.get("desktop_query") or data.get("query"))
        if normalized_action != "start":
            return self._failed(normalized_action, "Unsupported desktop action.")

        target = str(data.get("desktop_target") or data.get("query") or "").strip()
        if operation == "inspect_screen":
            return self._inspect_screen(target)
        if operation == "click_ui":
            return self._click_ui(target, str(data.get("desktop_query") or ""))
        if operation == "type_ui":
            return self._type_ui(target, str(data.get("desktop_query") or ""))
        if operation == "press_key":
            return self._press_key(target, str(data.get("desktop_query") or ""))
        if operation == "play_youtube":
            return self._play_youtube(target)
        if operation == "play_spotify":
            return self._play_spotify(target)
        if operation == "open_app":
            return self._open_app(target)
        if operation == "open_url":
            return self._open_url(target)
        if operation == "search_web":
            query = " ".join(target.split())
            if not query or len(query) > 500:
                return self._failed(normalized_action, "Provide a web-search query of 1–500 characters.")
            url = "https://www.google.com/search?q=" + quote_plus(query)
            result = self._open_url(url)
            if result.get("success"):
                result["result"] = {
                    "title": "Web search opened",
                    "query": query,
                    "url": url,
                }
            return result
        if operation == "open_folder":
            return self._open_folder(target)
        if operation == "open_file":
            return self._open_file(target)
        return self._failed(
            normalized_action,
            "Unsupported desktop operation. Supported operations are open_app, open_url, search_web, "
            "open_folder, open_file, find_files, list_files, inspect_screen, click_ui, type_ui, press_key, play_youtube, and play_spotify.",
        )

    @staticmethod
    def _ui_name(control: object) -> str:
        """Return a bounded accessibility label; never extract an edit's value."""
        try:
            info = getattr(control, "element_info", None)
            value = getattr(info, "name", "") if info is not None else ""
            if not value:
                value = control.window_text()  # type: ignore[attr-defined]
            return " ".join(str(value or "").split())[:160]
        except Exception:
            return ""

    @staticmethod
    def _ui_type(control: object) -> str:
        try:
            info = getattr(control, "element_info", None)
            return str(getattr(info, "control_type", "") or "")
        except Exception:
            return ""

    @staticmethod
    def _ui_control_enabled(control: object) -> bool:
        try:
            return bool(control.is_enabled()) and bool(control.is_visible())  # type: ignore[attr-defined]
        except Exception:
            return False

    @staticmethod
    def _ui_blocked_action_name(name: str) -> bool:
        label = " ".join(str(name or "").strip().casefold().split())
        blocked_exact = {
            "send", "send email", "send message", "delete", "delete message",
            "delete email", "remove", "clear conversation", "empty trash",
            "pay", "pay now", "purchase", "buy now", "place order", "submit order",
            "confirm payment", "transfer", "publish", "post", "share publicly",
            "approve", "accept payment", "log out", "sign out", "disconnect account",
            "trash", "move to trash", "archive", "mark as spam", "report spam", "forward",
        }
        if label in blocked_exact:
            return True
        # Button labels vary by site ("Send now", "Submit payment", etc.);
        # match dangerous verbs anywhere in the accessible label, not only exact names.
        return bool(re.search(
            r"\b(?:send|delete|remove|pay|purchase|buy|order|submit|publish|post|approve|transfer|confirm|share|unsubscribe|reject|forward|archive|trash|spam|report|empty|clear|allow|grant|authorize|authorization|permission|verify|verification|install|credential|credentials|log\s+in|sign\s+in|login|log\s+out|sign\s+out|disconnect|like|follow|subscribe|comment|reply|react|vote|invite|accept|join|connect|unfriend|friend\s+request|cancel|block|ban|leave|revoke|erase|wipe|reset|mute|kick|expel|withdraw|unfollow)\b",
            label,
            flags=re.IGNORECASE,
        ))

    def _uia_desktop(self):
        """Load Windows UI Automation only when a UI action is requested."""
        if self.platform_name != "nt":
            raise RuntimeError("Windows UI Automation is available only on Windows.")
        try:
            from pywinauto import Desktop
        except ImportError as exc:
            raise RuntimeError(
                "Windows UI Automation dependency pywinauto is not installed."
            ) from exc
        return Desktop(backend="uia")

    def _uia_windows(self, desktop, window_title: str = "") -> list:
        windows = list(desktop.windows(visible_only=True, enabled_only=True))
        title_filter = " ".join(str(window_title or "").strip().casefold().split())
        if title_filter:
            windows = [
                window for window in windows
                if title_filter in " ".join(self._ui_name(window).casefold().split())
                or title_filter in " ".join(str(window.window_text() or "").casefold().split())
            ]
        return windows

    def _activate_browser_tab(self, desktop, requested_tab: str):
        """Activate one uniquely matching browser tab when the user names an inactive tab."""
        needle = " ".join(str(requested_tab or "").strip().casefold().split())
        if not needle:
            return None
        browser_windows = []
        for window in desktop.windows(visible_only=True, enabled_only=True):
            title = " ".join(str(window.window_text() or "").casefold().split())
            if any(browser in title for browser in ("opera", "chrome", "edge", "firefox")):
                browser_windows.append(window)
        tab_matches = []
        for window in browser_windows[:8]:
            try:
                for control in window.descendants()[:1200]:
                    if (
                        self._ui_type(control) != "TabItem"
                        or not self._ui_control_enabled(control)
                    ):
                        continue
                    name = self._ui_name(control)
                    cleaned_name = re.sub(r"^\(\d+\)\s*", "", name).casefold().strip()
                    if cleaned_name == needle or needle in cleaned_name:
                        tab_matches.append((window, control))
                        if len(tab_matches) > 1:
                            break
            except Exception:
                continue
            if len(tab_matches) > 1:
                break
        if len(tab_matches) != 1:
            return None
        window, tab = tab_matches[0]
        try:
            tab.click_input()
        except Exception:
            return None
        return window

    @staticmethod
    def _ui_control_priority(control_type: str, name: str) -> tuple[int, str]:
        """Show in-app controls before browser chrome in the spoken inspection summary."""
        label = " ".join(str(name or "").casefold().split())
        chrome_noise = {
            "minimize", "maximize", "restore", "close", "back", "forward",
            "reload", "refresh", "tab island handle", "new tab", "search tabs",
            "reader mode", "submit feedback", "pinboards", "snapshot",
            "privacy protection", "send to my flow", "add to bookmarks",
            "easy setup", "extensions", "opera account signed-in",
        }
        if label in chrome_noise:
            rank = 8
        else:
            rank = {
                "Edit": 0,
                "ComboBox": 0,
                "Hyperlink": 1,
                "ListItem": 1,
                "MenuItem": 1,
                "TreeItem": 1,
                "Document": 1,
                "DataItem": 1,
                "Custom": 2,
                "Button": 2,
                "CheckBox": 2,
                "RadioButton": 2,
                "Text": 3,
                "TabItem": 5,
                "Tab": 6,
                "List": 6,
                "Window": 7,
            }.get(control_type, 7)
        return rank, label

    @staticmethod
    def _uia_children(control: object) -> list:
        try:
            return list(control.children())  # type: ignore[attr-defined]
        except Exception:
            return []

    def _inspect_screen(self, requested_window: str = "") -> dict:
        """Return visible window titles and actionable accessibility labels only."""
        try:
            desktop = self._uia_desktop()
            windows = self._uia_windows(desktop, requested_window)
            if requested_window and not windows:
                activated = self._activate_browser_tab(desktop, requested_window)
                windows = self._uia_windows(desktop, requested_window)
                if not windows and activated is not None:
                    windows = [activated]
        except Exception as exc:
            return self._failed(
                "start",
                "NOVA could not inspect the Windows accessibility tree. "
                "Ensure the desktop session is unlocked and UI Automation is available.",
                result={"error_type": type(exc).__name__},
            )
        if requested_window and not windows:
            return self._failed(
                "start",
                f"No visible window or unique browser tab matched '{requested_window}'.",
            )

        visible = []
        useful_types = {
            "Button", "Hyperlink", "TabItem", "MenuItem", "ListItem",
            "Edit", "ComboBox", "CheckBox", "RadioButton", "TreeItem",
            "List", "Tab", "Window", "Text", "Document", "DataItem", "Custom",
        }
        for window in windows[:8]:
            try:
                title = " ".join(str(window.window_text() or "").split())[:160]
                discovered = {}
                for control in window.descendants()[:1200]:
                    name = self._ui_name(control)
                    control_type = self._ui_type(control)
                    if (
                        not name
                        or control_type not in useful_types
                        or not self._ui_control_enabled(control)
                    ):
                        continue
                    key = (control_type, name.casefold())
                    discovered.setdefault(key, {
                        "name": name,
                        "control_type": control_type,
                    })
                controls = sorted(
                    discovered.values(),
                    key=lambda item: self._ui_control_priority(
                        item["control_type"], item["name"]
                    ),
                )[:35]
                visible.append({"window_title": title, "controls": controls})
            except Exception:
                continue
        if not visible:
            return self._failed(
                "start",
                "No readable, actionable controls were exposed by the visible Windows UI.",
            )
        return self._succeed(
            "start",
            "Inspected visible Windows controls",
            windows=visible,
            window_count=len(visible),
        )

    def _click_ui(self, control_name: str, window_title: str = "") -> dict:
        """Click one uniquely labelled safe UI control; never guess a coordinate."""
        label = " ".join(str(control_name or "").strip().split())
        if not label or len(label) > 160:
            return self._failed("start", "Provide the exact accessible name of the UI control.")
        if self._ui_blocked_action_name(label):
            return self._failed(
                "start",
                "This control can send, delete, publish, pay, approve, or otherwise commit an external change. "
                "Use the dedicated confirmation-protected workflow instead.",
            )
        safe_types = {
            "Button", "Hyperlink", "TabItem", "MenuItem", "ListItem",
            "CheckBox", "RadioButton", "TreeItem", "Edit", "ComboBox",
        }
        try:
            desktop = self._uia_desktop()
            windows = self._uia_windows(desktop, window_title)
            if window_title and not windows:
                activated = self._activate_browser_tab(desktop, window_title)
                windows = self._uia_windows(desktop, window_title)
                if not windows and activated is not None:
                    windows = [activated]
            candidates = []
            for window in windows[:12]:
                for control in window.descendants()[:800]:
                    if (
                        self._ui_name(control).casefold() == label.casefold()
                        and self._ui_type(control) in safe_types
                        and self._ui_control_enabled(control)
                    ):
                        candidates.append((window, control))
                        if len(candidates) > 1:
                            break
                if len(candidates) > 1:
                    break
            if len(candidates) != 1:
                if not candidates:
                    return self._failed(
                        "start",
                        f"No unique visible, enabled UI control named '{label}' was found.",
                    )
                return self._failed(
                    "start",
                    f"More than one visible control is named '{label}'. Specify the app/window to disambiguate.",
                    result={"match_count": len(candidates)},
                )
            window, control = candidates[0]
            window_title_value = str(window.window_text() or "")[:160]
            blocked_window_terms = (
                "user account control", "uac prompt", "windows security",
                "security confirmation", "credential prompt", "permission required",
                "authorize access", "elevated administrator",
            )
            if any(term in window_title_value.casefold() for term in blocked_window_terms):
                return self._failed(
                    "start",
                    "NOVA will not click through an operating-system security, credential, or permission prompt.",
                    result={"window_title": window_title_value},
                )
            control.click_input()
        except Exception as exc:
            return self._failed(
                "start",
                f"NOVA could not safely click the requested UI control '{label}'.",
                result={"error_type": type(exc).__name__},
            )
        return self._succeed(
            "start",
            f"Clicked {label}",
            operation="click_ui",
            control_name=label,
            control_type=self._ui_type(control),
            window_title=window_title_value,
        )

    def _type_ui(self, field_name: str, text_to_type: str) -> dict:
        """Enter text only in one labelled, visible, non-sensitive edit field."""
        label = " ".join(str(field_name or "").strip().split())
        value = str(text_to_type or "")
        window_filter = ""
        field_context = re.fullmatch(
            r"(?P<field>.+?)\s+(?:in|on|inside)\s+(?:the\s+)?(?P<window>.+)",
            label,
            flags=re.IGNORECASE,
        )
        if field_context:
            label = field_context.group("field").strip()
            window_filter = field_context.group("window").strip()
        if not label or len(label) > 160 or len(window_filter) > 160:
            return self._failed("start", "Specify the exact accessible name of the input field.")
        if not value or len(value) > 2000 or any(
            ord(char) < 32 and char not in "\t\r\n" for char in value
        ):
            return self._failed("start", "Provide text of 1–2000 printable characters.")
        sensitive_terms = (
            "password", "passcode", "security code", "verification code",
            "one-time code", "otp", "credit card", "cvv", "bank account",
            "recovery code", "private key", "access token",
        )
        if any(term in label.casefold() for term in sensitive_terms):
            return self._failed(
                "start",
                "For privacy and security, the generic UI typer won't enter passwords, codes, card details, or tokens.",
            )
        requested_label = label.casefold()
        label_aliases = {
            "search bar": {"search bar", "search", "search box", "address and search bar", "search the web and type a url"},
            "search box": {"search box", "search", "search bar", "address and search bar", "search the web and type a url"},
            "address bar": {"address bar", "address and search bar", "search the web and type a url"},
            "url bar": {"url bar", "address and search bar", "search the web and type a url"},
        }
        accepted_labels = label_aliases.get(requested_label, {requested_label})
        try:
            desktop = self._uia_desktop()
            field_windows = self._uia_windows(desktop, window_filter)
            if window_filter and not field_windows:
                activated = self._activate_browser_tab(desktop, window_filter)
                field_windows = self._uia_windows(desktop, window_filter)
                if not field_windows and activated is not None:
                    field_windows = [activated]
            candidates = []
            for window in field_windows[:12]:
                for control in window.descendants()[:800]:
                    if (
                        self._ui_name(control).casefold() in accepted_labels
                        and self._ui_type(control) in {"Edit", "ComboBox"}
                        and self._ui_control_enabled(control)
                    ):
                        candidates.append((window, control))
                        if len(candidates) > 1:
                            break
                if len(candidates) > 1:
                    break
            if len(candidates) != 1:
                if not candidates:
                    return self._failed(
                        "start",
                        f"No unique visible, enabled text field named '{label}' was found.",
                    )
                return self._failed(
                    "start",
                    f"More than one visible text field is named '{label}'. Use an exact, unambiguous field label.",
                    result={"match_count": len(candidates)},
                )
            window, control = candidates[0]
            window.set_focus()
            try:
                control.set_edit_text(value)
            except Exception:
                control.click_input()
                control.type_keys("^a", set_foreground=True)
                control.type_keys(value, with_spaces=True, set_foreground=True)
            window_title_value = str(window.window_text() or "")[:160]
        except Exception as exc:
            return self._failed(
                "start",
                f"NOVA could not enter text into the uniquely matched field '{label}'.",
                result={"error_type": type(exc).__name__},
            )
        return self._succeed(
            "start",
            f"Entered text in {label}",
            operation="type_ui",
            field_name=label,
            window_title=window_title_value,
            character_count=len(value),
        )

    def _press_key(self, key_name: str, window_title: str = "") -> dict:
        """Send a small, explicit set of non-destructive keyboard shortcuts."""
        normalized = re.sub(r"\s+", "", str(key_name or "").upper()).replace("CONTROL+", "CTRL+")
        key_map = {
            "CTRL+L": "^l",
            "CTRL+F": "^f",
            "CTRL+A": "^a",
            "CTRL+C": "^c",
            "CTRL+V": "^v",
            "ESC": "{ESC}",
            "TAB": "{TAB}",
            "SHIFT+TAB": "+{TAB}",
            "SPACE": "{SPACE}",
            "BACKSPACE": "{BACKSPACE}",
            "UP": "{UP}",
            "DOWN": "{DOWN}",
            "LEFT": "{LEFT}",
            "RIGHT": "{RIGHT}",
            "HOME": "{HOME}",
            "END": "{END}",
            "F5": "{F5}",
        }
        if normalized == "ENTER":
            normalized = "ENTER"
        else:
            normalized = normalized.replace("ESCAPE", "ESC")
        key_sequence = key_map.get(normalized)
        if normalized in {"ENTER", "SPACE"}:
            # Enter/Space can activate the focused button; require an explicit
            # target window and reject message/financial/social action windows.
            if not str(window_title or "").strip():
                return self._failed(
                    "start",
                    "Enter/Space can activate a focused control. Specify a safe target window or use its labelled control.",
                )
            key_sequence = "{ENTER}" if normalized == "ENTER" else "{SPACE}"
        if key_sequence is None:
            return self._failed(
                "start",
                "That key isn't on NOVA's safe keyboard allowlist.",
                result={"allowed_keys": sorted((*key_map.keys(), "ENTER"))},
            )
        try:
            desktop = self._uia_desktop()
            windows = self._uia_windows(desktop, window_title)
            if window_title and not windows:
                activated = self._activate_browser_tab(desktop, window_title)
                windows = self._uia_windows(desktop, window_title)
                if not windows and activated is not None:
                    windows = [activated]
            if window_title:
                if len(windows) != 1:
                    return self._failed(
                        "start",
                        "Specify one visible window title before sending a keyboard shortcut.",
                        result={"match_count": len(windows)},
                    )
                actual_title = str(windows[0].window_text() or "").casefold()
                blocked_activation_window_terms = (
                    "gmail", "outlook", "whatsapp", "message", "messages", "mail",
                    "webmail", "teams", "slack", "discord", "telegram", "messenger",
                    "signal", "chat", "bank", "payment", "checkout", "compose",
                    "linkedin", "facebook", "instagram", "youtube", "twitter", "x.com",
                    "reddit", "tiktok", "social", "user account control", "uac prompt",
                    "windows security", "security confirmation", "credential prompt",
                    "permission required",
                )
                if normalized in {"ENTER", "SPACE"} and any(
                    item in actual_title for item in blocked_activation_window_terms
                ):
                    return self._failed(
                        "start",
                        "Enter/Space is blocked in email, message, payment, checkout, social, or operating-system security windows.",
                        result={"window_title": str(windows[0].window_text() or "")[:160]},
                    )
                windows[0].set_focus()
            else:
                desktop.get_active().set_focus()
            from pywinauto.keyboard import send_keys
            send_keys(key_sequence, with_spaces=True)
        except Exception as exc:
            return self._failed(
                "start",
                "NOVA could not send the allowlisted key to the requested window.",
                result={"error_type": type(exc).__name__},
            )
        return self._succeed(
            "start",
            f"Pressed {normalized}",
            operation="press_key",
            key=normalized,
            window_title=" ".join(str(window_title or "").split())[:160] or None,
        )

    def _open_app(self, requested: str) -> dict:
        label = " ".join(str(requested or "").strip().lower().split())
        if (
            not label
            or len(label) > 80
            or any(char in label for char in ("/", "\\", ":", ";", "|", "<", ">", "\"", "'"))
            or re.search(r"\s+-(?:command|encodedcommand|executionpolicy|file)\b", label)
        ):
            return self._failed(
                "start",
                "Give NOVA an application name only; arbitrary shell commands, paths, and arguments are not on the allowlist.",
            )

        app = self.APP_ALIASES.get(label)
        if not app:
            return self._open_start_menu_app(label)

        if app == "spotify":
            # Prefer an installed native Spotify shortcut when one exists. If it is
            # not installed, fall back to the browser player rather than failing a
            # perfectly clear request to open Spotify.
            native_result = self._open_start_menu_app(label)
            if native_result.get("success") is True:
                return native_result
            if "No installed Start Menu shortcut" not in str(native_result.get("error") or ""):
                return native_result
            web_result = self._open_url("https://open.spotify.com/")
            if web_result.get("success") is True:
                return self._succeed(
                    "start",
                    "Opened Spotify Web Player",
                    operation="open_app",
                    application="Spotify Web Player",
                    url="https://open.spotify.com/",
                    launch_source="browser_fallback",
                )
            return web_result
        if app == "microsoft_store":
            candidates = [[
                "explorer.exe",
                "shell:AppsFolder\\Microsoft.WindowsStore_8wekyb3d8bbwe!App",
            ]]
        elif app == "calculator":
            candidates = [["calc.exe"]]
        elif app == "notepad":
            candidates = [["notepad.exe"]]
        elif app == "explorer":
            candidates = [["explorer.exe"]]
        elif app in {"chrome", "edge", "firefox"}:
            candidates = self._browser_candidates(app)
        else:
            candidates = self._office_candidates(app)

        last_error: Exception | None = None
        for command in candidates:
            try:
                self._process_launcher(command)
                return self._succeed(
                    "start",
                    f"Opened {label.title()}",
                    operation="open_app",
                    application=label,
                    launch_source="known_application",
                )
            except (OSError, subprocess.SubprocessError) as exc:
                last_error = exc

        return self._failed(
            "start",
            f"{label.title()} could not be launched. It may not be installed.",
            result={"application": label, "error_type": type(last_error).__name__ if last_error else None},
        )

    def _open_start_menu_app(self, requested: str) -> dict:
        """Launch an exact installed-app shortcut without executing user-supplied commands."""
        label = " ".join(str(requested or "").strip().split())
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._()+#-]{0,79}", label)
            or re.search(r"\s+-(?:command|encodedcommand|executionpolicy|file)\b", label, re.IGNORECASE)
        ):
            return self._failed(
                "start",
                "That application name is not valid. Arbitrary commands and arguments are not on the allowlist.",
            )

        app_data = os.environ.get("APPDATA") or str(
            Path.home() / "AppData" / "Roaming"
        )
        program_data = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
        roots = (
            Path(app_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
            Path(program_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        )

        matches: list[Path] = []
        scanned = 0
        for root in roots:
            try:
                if not root.is_dir():
                    continue
                for shortcut in root.rglob("*.lnk"):
                    scanned += 1
                    if scanned > 4000:
                        break
                    if shortcut.is_file() and shortcut.stem.casefold() == label.casefold():
                        matches.append(shortcut)
                        if len(matches) > 1:
                            break
                if scanned > 4000 or len(matches) > 1:
                    break
            except OSError:
                continue

        if len(matches) > 1:
            return self._failed(
                "start",
                f"More than one Start Menu shortcut is named '{label}'. Tell NOVA the exact app name shown in Start Menu.",
                result={"application": label, "match_count": len(matches)},
            )
        if not matches:
            return self._failed(
                "start",
                f"No installed Start Menu shortcut named '{label}' was found. Try the exact application name or a supported built-in app.",
                result={"application": label, "searched_start_menu": True},
            )

        shortcut = matches[0]
        try:
            self._file_opener(str(shortcut))
        except (OSError, subprocess.SubprocessError) as exc:
            return self._failed(
                "start",
                f"NOVA found '{shortcut.stem}' in Start Menu but Windows could not launch its shortcut.",
                result={"application": shortcut.stem, "error_type": type(exc).__name__},
            )
        return self._succeed(
            "start",
            f"Opened {shortcut.stem}",
            operation="open_app",
            application=shortcut.stem,
            launch_source="start_menu",
        )

    def _browser_candidates(self, browser: str) -> list[list[str]]:
        executable = {"chrome": "chrome.exe", "edge": "msedge.exe", "firefox": "firefox.exe"}[browser]
        located = shutil.which(executable)
        if located:
            return [[located]]

        env = os.environ
        program_files = [
            env.get("ProgramFiles", r"C:\Program Files"),
            env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ]
        local_app_data = env.get("LOCALAPPDATA", "")
        known_paths = {
            "chrome": [
                *(Path(root) / "Google" / "Chrome" / "Application" / executable for root in program_files),
                Path(local_app_data) / "Google" / "Chrome" / "Application" / executable,
            ],
            "edge": [
                *(Path(root) / "Microsoft" / "Edge" / "Application" / executable for root in program_files),
                Path(local_app_data) / "Microsoft" / "Edge" / "Application" / executable,
            ],
            "firefox": [
                *(Path(root) / "Mozilla Firefox" / executable for root in program_files),
                Path(local_app_data) / "Mozilla Firefox" / executable,
            ],
        }
        return [[str(path)] for path in known_paths[browser] if path.is_file()]

    def _office_candidates(self, application: str) -> list[list[str]]:
        executable_names = {
            "outlook": "OUTLOOK.EXE",
            "word": "WINWORD.EXE",
            "excel": "EXCEL.EXE",
            "powerpoint": "POWERPNT.EXE",
        }
        executable = executable_names[application]
        located = shutil.which(executable)
        if located:
            return [[located]]

        env = os.environ
        program_files = [
            env.get("ProgramFiles", r"C:\Program Files"),
            env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ]
        candidates = []
        for root in program_files:
            office_roots = (
                Path(root) / "Microsoft Office" / "root" / "Office16",
                Path(root) / "Microsoft Office" / "Office16",
                Path(root) / "Microsoft Office" / "Office15",
            )
            for office_root in office_roots:
                path = office_root / executable
                if path.is_file():
                    candidates.append([str(path)])
        return candidates

    def _open_url(self, value: str) -> dict:
        url = str(value or "").strip()
        if not url or len(url) > 2048 or any(char in url for char in "\r\n"):
            return self._failed("start", "Provide a valid HTTP(S) URL.")
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme.lower() not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("URL must use HTTP(S) and must not contain embedded credentials.")
        except ValueError:
            return self._failed("start", "Only valid HTTP(S) URLs without embedded credentials can be opened.")
        try:
            opened = bool(self._url_opener(url))
        except Exception:
            opened = False
        if not opened:
            return self._failed("start", "The default browser did not confirm that it opened the URL.")
        return self._succeed("start", "Opened website", operation="open_url", url=url)

    @staticmethod
    def _normalize_visible_text(value: object) -> str:
        return " ".join(re.sub(r"[^\w\s]", " ", str(value or "").casefold()).split())

    def _play_youtube(self, requested: str) -> dict:
        """Find one matching YouTube result and report success only if playback is observable."""
        query = " ".join(str(requested or "").strip().split())
        if len(query) < 2 or len(query) > 180 or any(ord(char) < 32 for char in query):
            return self._failed("start", "Tell NOVA the song or video title (2–180 printable characters).")

        normalized_query = self._normalize_visible_text(query)
        normalized_terms = normalized_query.split()
        latest_upload_requested = bool(
            re.search(r"\b(?:latest|newest|most\s+recent|recently\s+uploaded|recent)\b", normalized_query)
        )
        non_content_terms = {
            "song", "songs", "music", "video", "videos", "youtube", "play",
            "please", "official", "audio", "lyrics", "on", "in", "the", "a", "an",
            "ki", "ka", "ke", "koi", "kuch", "my", "any", "some", "from", "by",
            "latest", "newest", "most", "recent", "recently", "uploaded", "upload",
            "new", "latestly", "watch", "channel",
        }
        query_tokens = [
            token for token in normalized_terms
            if len(token) > 1 and token not in non_content_terms
        ]
        if not query_tokens or (len(query_tokens) == 1 and len(query_tokens[0]) < 4):
            return self._failed(
                "start",
                "That song or video request is too vague to choose safely. Say the specific title or creator.",
            )

        # "Latest video by a creator" should search that creator sorted by upload
        # date; plain relevance search can return old commentary or unrelated clips.
        if latest_upload_requested:
            # Preserve the user's exact query in the page title so we can
            # activate this specific tab even when several YouTube tabs are open.
            search_query = query
            search_url = (
                "https://www.youtube.com/results?search_query="
                + quote_plus(search_query, safe="")
                + "&sp=CAI%3D"
            )
        else:
            search_query = query
            search_url = "https://www.youtube.com/results?search_query=" + quote_plus(search_query, safe="")
        opened = self._open_url(search_url)
        if not opened.get("success"):
            return opened

        # Bound the UI wait so voice actions leave time for the spoken result.
        search_deadline = time.monotonic() + 6.0
        selected_title = ""
        selected_window_title = ""
        ui_error_type = None

        while time.monotonic() < search_deadline and not selected_title:
            try:
                desktop = self._uia_desktop()
                windows = self._uia_windows(desktop, "YouTube")
                query_hint = self._normalize_visible_text(query)
                active_tab_matches_request = any(
                    query_hint
                    and query_hint in self._normalize_visible_text(window.window_text())
                    for window in windows
                )
                if not active_tab_matches_request:
                    # A browser may already show another YouTube tab. Target the
                    # tab for this exact request rather than accepting any YouTube page.
                    self._activate_browser_tab(desktop, query)
                    windows = self._uia_windows(desktop, "YouTube")

                candidates: list[tuple[float, int, object, object, str, str]] = []
                creator_channel_matches: list[tuple[int, object, str]] = []
                video_title_links: list[tuple[int, object, object, str, str]] = []
                for window in windows[:8]:
                    window_title = " ".join(str(window.window_text() or "").split())[:160]
                    for index, control in enumerate(window.descendants()[:1600]):
                        if (
                            self._ui_type(control) not in {"Hyperlink", "ListItem"}
                            or not self._ui_control_enabled(control)
                        ):
                            continue
                        name = self._ui_name(control)
                        if not name or re.search(
                            r"\b(?:sponsored|advertisement|promoted)\b",
                            name,
                            flags=re.IGNORECASE,
                        ):
                            continue
                        normalized_name = self._normalize_visible_text(name)
                        # Record title links with a visible duration. They are more
                        # likely to be actual video links than channel/navigation links.
                        if re.search(
                            r"\b\d+\s*(?:seconds?|minutes?|hours?|days?)\b",
                            normalized_name,
                        ) and self._ui_type(control) == "Hyperlink":
                            video_title_links.append(
                                (index, window, control, name, window_title)
                            )

                        # A creator's channel link usually follows its video title in
                        # the accessibility tree (for example, "Go to channel MrBeast").
                        # Keep this metadata so a creator-only/latest request can pick
                        # that creator's adjacent video instead of clicking their channel.
                        channel_match = re.match(
                            r"^go to channel\s+(.+)$",
                            normalized_name,
                            flags=re.IGNORECASE,
                        )
                        if latest_upload_requested and channel_match:
                            channel_tokens = set(channel_match.group(1).split())
                            matching_channel_tokens = sum(
                                token in channel_tokens for token in query_tokens
                            )
                            if matching_channel_tokens / len(query_tokens) >= 0.8:
                                creator_channel_matches.append(
                                    (index, window, window_title)
                                )
                            continue

                        # A channel link is not a video, so don't select it just
                        # because the requested creator's name appears in its label.
                        if re.match(r"^(?:go to channel|channel)\b", normalized_name):
                            continue

                        name_tokens = set(normalized_name.split())
                        matching = sum(token in name_tokens for token in query_tokens)
                        score = matching / len(query_tokens)
                        if score < 0.8:
                            continue
                        candidates.append(
                            (score, index, window, control, name, window_title)
                        )

                if not candidates and latest_upload_requested and creator_channel_matches:
                    # YouTube's upload-date filter orders results newest-first.
                    # For a matching creator, choose the nearest video-title link
                    # preceding that creator's channel link in the same result card.
                    for channel_index, channel_window, channel_window_title in sorted(
                        creator_channel_matches, key=lambda item: item[0]
                    ):
                        adjacent_titles = [
                            item for item in video_title_links
                            if item[1] is channel_window
                            and item[0] < channel_index
                            and channel_index - item[0] <= 80
                        ]
                        if adjacent_titles:
                            index, window, control, name, window_title = max(
                                adjacent_titles, key=lambda item: item[0]
                            )
                            candidates.append(
                                (1.0, index, window, control, name, window_title)
                            )
                            break

                if candidates:
                    # Highest lexical match wins; in equal scores preserve visual/UIA
                    # order (the first result in the browser's accessibility tree).
                    candidates.sort(key=lambda item: (-item[0], item[1]))
                    _, _, window, control, name, window_title = candidates[0]
                    try:
                        window.set_focus()
                        control.click_input()
                    except Exception as exc:
                        return self._failed(
                            "start",
                            "I opened YouTube search results but couldn't safely open the matching video.",
                            result={
                                "query": query,
                                "search_url": search_url,
                                "selected_title": name,
                                "error_type": type(exc).__name__,
                            },
                        )
                    selected_title = name
                    selected_window_title = window_title
                else:
                    time.sleep(0.25)
            except Exception as exc:
                ui_error_type = type(exc).__name__
                time.sleep(0.25)

        if not selected_title:
            return self._failed(
                "start",
                "I opened YouTube search results, but couldn't identify an accessible result matching that title. "
                "I did not claim that playback started.",
                result={
                    "query": query,
                    "search_url": search_url,
                    "search_opened": True,
                    "error_type": ui_error_type,
                },
            )

        playback_deadline = time.monotonic() + 5.0
        while time.monotonic() < playback_deadline:
            try:
                desktop = self._uia_desktop()
                windows = self._uia_windows(desktop, "YouTube")
                if not windows:
                    self._activate_browser_tab(desktop, selected_title)
                    windows = self._uia_windows(desktop, "YouTube")

                selected_title_tokens = set(
                    self._normalize_visible_text(selected_title).split()
                )
                for window in windows[:8]:
                    window_title = " ".join(str(window.window_text() or "").split())[:160]
                    title_tokens = set(self._normalize_visible_text(window_title).split())
                    # Repeated words (for example, "Pal Pal") are one
                    # distinct title token for verification. Counting both
                    # occurrences makes a correctly playing result impossible
                    # to verify when the browser title contains the song name
                    # but omits extra result-label words such as "Official Audio".
                    title_matches = (
                        len(selected_title_tokens & title_tokens)
                        >= max(1, min(2, len(set(query_tokens))))
                    )
                    if not title_matches:
                        continue
                    controls = window.descendants()[:1600]
                    is_playing = any(
                        self._ui_type(control) == "Button"
                        and bool(re.match(
                            r"^\s*pause(?:\s|\(|$)",
                            self._ui_name(control),
                            flags=re.IGNORECASE,
                        ))
                        and self._ui_control_enabled(control)
                        for control in controls
                    )
                    if is_playing:
                        return self._succeed(
                            "start",
                            "YouTube playback verified",
                            operation="play_youtube",
                            query=query,
                            video_title=selected_title,
                            window_title=window_title,
                            search_url=search_url,
                            playback_verified=True,
                        )
                time.sleep(0.25)
            except Exception:
                time.sleep(0.25)

        return self._failed(
            "start",
            "I opened the matching YouTube result, but couldn't verify that it is playing. "
            "Please check the player before assuming playback started.",
            result={
                "query": query,
                "video_title": selected_title,
                "window_title": selected_window_title,
                "search_url": search_url,
                "playback_verified": False,
            },
        )

    def _play_spotify(self, requested: str) -> dict:
        """Open Spotify Web Player, select a matching track, and verify playback."""
        query = " ".join(str(requested or "").strip().split())
        if len(query) < 2 or len(query) > 180 or any(ord(char) < 32 for char in query):
            return self._failed("start", "Tell NOVA the song title (2–180 printable characters).")

        search_url = "https://open.spotify.com/search/" + quote_plus(query, safe="")
        opened = self._open_url(search_url)
        if not opened.get("success"):
            return opened

        normalized_query = self._normalize_visible_text(query)
        query_tokens = list(dict.fromkeys(
            token for token in normalized_query.split()
            if len(token) > 1 and token not in {"song", "track", "music", "the", "a", "on", "spotify"}
        ))
        if not query_tokens:
            return self._failed(
                "start",
                "I opened Spotify, but the song title was too vague to select safely.",
                result={"query": query, "search_url": search_url},
            )

        # Keep song selection bounded to protect the realtime voice response budget.
        selection_deadline = time.monotonic() + 6.0
        selected_title = ""
        selected_window_title = ""
        selection_error = None

        while time.monotonic() < selection_deadline and not selected_title:
            try:
                desktop = self._uia_desktop()
                windows = self._uia_windows(desktop, "Spotify")
                for window in windows[:8]:
                    window_title = " ".join(str(window.window_text() or "").split())[:160]
                    controls = window.descendants()[:1600]
                    play_buttons = []
                    result_links = []
                    for index, control in enumerate(controls):
                        control_type = self._ui_type(control)
                        if control_type not in {"Button", "Hyperlink", "ListItem"}:
                            continue
                        if not self._ui_control_enabled(control):
                            continue
                        name = self._ui_name(control)
                        if not name:
                            continue
                        normalized_name = self._normalize_visible_text(name)
                        matching = sum(token in normalized_name.split() for token in query_tokens)
                        score = matching / len(query_tokens)
                        if score < 0.8:
                            continue
                        if control_type == "Button" and re.search(
                            r"\bplay\b", normalized_name, flags=re.IGNORECASE
                        ):
                            play_buttons.append((score, index, control, name, window_title))
                        elif control_type in {"Hyperlink", "ListItem"}:
                            result_links.append((score, index, control, name, window_title))

                    if play_buttons:
                        play_buttons.sort(key=lambda item: (-item[0], item[1]))
                        best_score = play_buttons[0][0]
                        best = [item for item in play_buttons if item[0] == best_score]
                        if len(best) == 1:
                            _, _, control, name, window_title = best[0]
                            window.set_focus()
                            control.click_input()
                            selected_title = name
                            selected_window_title = window_title
                            break
                    if result_links:
                        result_links.sort(key=lambda item: (-item[0], item[1]))
                        best_score = result_links[0][0]
                        best = [item for item in result_links if item[0] == best_score]
                        if len(best) == 1:
                            _, _, control, name, window_title = best[0]
                            window.set_focus()
                            control.click_input()
                            selected_title = name
                            selected_window_title = window_title
                            break
                if not selected_title:
                    time.sleep(0.25)
            except Exception as exc:
                selection_error = type(exc).__name__
                time.sleep(0.25)

        if not selected_title:
            return self._failed(
                "start",
                "Spotify search opened, but I couldn't identify one accessible result matching that song. I did not claim playback started.",
                result={"query": query, "search_url": search_url, "error_type": selection_error},
            )

        playback_deadline = time.monotonic() + 5.0
        while time.monotonic() < playback_deadline:
            try:
                desktop = self._uia_desktop()
                windows = self._uia_windows(desktop, "Spotify")
                for window in windows[:8]:
                    controls = window.descendants()[:1600]
                    is_playing = any(
                        self._ui_type(control) == "Button"
                        and bool(re.match(r"^\s*pause(?:\s|\(|$)", self._normalize_visible_text(self._ui_name(control)), flags=re.IGNORECASE))
                        and self._ui_control_enabled(control)
                        for control in controls
                    )
                    if is_playing:
                        return self._succeed(
                            "start",
                            "Spotify playback verified",
                            operation="play_spotify",
                            query=query,
                            track_title=re.sub(r"^\s*(?:play|pause)\s+", "", selected_title, flags=re.IGNORECASE).strip() or query,
                            window_title=" ".join(str(window.window_text() or "").split())[:160],
                            search_url=search_url,
                            playback_verified=True,
                        )
                time.sleep(0.25)
            except Exception:
                time.sleep(0.25)

        return self._failed(
            "start",
            "I opened Spotify and selected a matching result, but couldn't verify playback. Please check the player before assuming the song started.",
            result={
                "query": query,
                "track_title": selected_title,
                "window_title": selected_window_title,
                "search_url": search_url,
                "playback_verified": False,
            },
        )

    def _list_files(self, value: object) -> dict:
        """List recent files in one explicit user folder; never traverse the whole disk."""
        label = " ".join(str(value or "").strip().casefold().split())
        folder_name = self.FOLDER_NAMES.get(label)
        if not folder_name:
            return self._failed(
                "search",
                "Choose one of the user folders: Desktop, Documents, Downloads, Pictures, Music, or Videos.",
            )
        root = self.home_directory / folder_name
        try:
            if not root.is_dir():
                return self._failed("search", f"The {folder_name} folder is not available.")
            allowed_root = root.resolve()
        except OSError:
            return self._failed("search", f"The {folder_name} folder is not available.")

        found: list[dict] = []
        scanned = 0
        truncated = False
        for current, directories, files in os.walk(root, followlinks=False):
            safe_directories = []
            for directory_name in directories:
                directory_path = Path(current) / directory_name
                if (
                    directory_name.startswith(".")
                    or directory_name.casefold() in self.SKIP_DIRECTORIES
                    or directory_path.is_symlink()
                    or (
                        callable(getattr(directory_path, "is_junction", None))
                        and directory_path.is_junction()
                    )
                ):
                    continue
                safe_directories.append(directory_name)
            directories[:] = safe_directories

            for name in files:
                scanned += 1
                if name.startswith("."):
                    continue
                path = Path(current) / name
                try:
                    resolved_path = path.resolve(strict=True)
                    if not resolved_path.is_file() or not resolved_path.is_relative_to(allowed_root):
                        continue
                    stat = resolved_path.stat()
                except (OSError, RuntimeError):
                    continue
                found.append({
                    "name": name,
                    "path": str(resolved_path),
                    "extension": resolved_path.suffix.lower(),
                    "size_bytes": int(stat.st_size),
                    "modified_epoch": float(stat.st_mtime),
                    "modified_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                    "incomplete_download": resolved_path.suffix.casefold() == ".crdownload",
                })
                if scanned >= self.MAX_SEARCHED_FILES:
                    truncated = True
                    break
            if truncated:
                break

        found.sort(key=lambda item: float(item["modified_epoch"]), reverse=True)
        total_count = len(found)
        files_to_show = found[:25]
        for item in files_to_show:
            item.pop("modified_epoch", None)
        return self._succeed(
            "search",
            f"Listed recent files in {folder_name}",
            operation="list_files",
            folder=folder_name,
            files=files_to_show,
            count=total_count,
            shown_count=len(files_to_show),
            truncated=truncated or total_count > len(files_to_show),
            scanned_files=scanned,
        )

    def _search_roots(self, *, include_profile: bool = False) -> list[Path]:
        # CV/resume discovery may search the user's profile (including OneDrive
        # and user-created folders); os.walk below excludes hidden/app/system
        # directories and still applies a fixed file-count/result cap.
        if include_profile:
            try:
                return [self.home_directory.resolve()] if self.home_directory.is_dir() else []
            except OSError:
                return []

        roots: list[Path] = []
        for folder in self.FOLDER_NAMES.values():
            path = self.home_directory / folder
            try:
                if path.is_dir():
                    roots.append(path.resolve())
            except OSError:
                continue
        return roots

    def _find_files(self, value: object) -> dict:
        query = " ".join(str(value or "").split()).strip()
        if len(query) < 2 or len(query) > 120 or "/" in query or "\\" in query or query in {".", ".."}:
            return self._failed("search", "Use a file-name search of 2–120 characters, not a folder path.")
        normalized_query = query.casefold()
        cv_search = normalized_query in {
            "cv", "cvs", "cv file", "cv files", "resume", "resumes",
            "resume file", "resume files", "curriculum vitae",
        }
        roots = self._search_roots(include_profile=cv_search)
        if not roots:
            return self._failed("search", "NOVA could not find accessible user folders.")

        found: list[dict[str, str]] = []
        scanned = 0
        truncated = False
        needle = query.casefold()
        for root in roots:
            for current, directories, files in os.walk(root, followlinks=False):
                safe_directories = []
                for directory_name in directories:
                    directory_path = Path(current) / directory_name
                    if (
                        directory_name.casefold() in self.SKIP_DIRECTORIES
                        or directory_name.startswith(".")
                        or directory_path.is_symlink()
                        or (
                            callable(getattr(directory_path, "is_junction", None))
                            and directory_path.is_junction()
                        )
                    ):
                        continue
                    safe_directories.append(directory_name)
                if cv_search:
                    preferred_directories = {
                        "onedrive", "documents", "desktop", "downloads",
                        "career", "careers", "resume", "resumes", "cv", "cvs",
                        "work", "jobs", "personal",
                    }
                    safe_directories.sort(
                        key=lambda item: (
                            0 if item.casefold() in preferred_directories else 1,
                            item.casefold(),
                        )
                    )
                directories[:] = safe_directories

                for name in files:
                    scanned += 1
                    filename_key = name.casefold()
                    if cv_search:
                        extension = Path(name).suffix.casefold()
                        filename_stem = Path(name).stem.casefold()
                        matches_name = (
                            extension in self.CV_SEARCH_EXTENSIONS
                            and bool(self.CV_FILENAME_PATTERN.search(filename_stem))
                        )
                    else:
                        matches_name = needle in filename_key
                    if matches_name:
                        path = Path(current) / name
                        try:
                            resolved_path = path.resolve(strict=True)
                        except (OSError, RuntimeError):
                            resolved_path = None
                        if (
                            resolved_path is not None
                            and resolved_path.is_file()
                            and any(
                                resolved_path.is_relative_to(allowed_root)
                                for allowed_root in roots
                            )
                        ):
                            found.append({
                                "name": name,
                                "path": str(resolved_path),
                                "extension": resolved_path.suffix.lower(),
                            })
                            if len(found) >= self.MAX_RESULTS:
                                truncated = True
                                break
                    if scanned >= self.MAX_SEARCHED_FILES:
                        truncated = True
                        break
                if truncated:
                    break
            if truncated:
                break

        return self._succeed(
            "search",
            f"Found {len(found)} matching file(s)",
            operation="find_files",
            query=query,
            files=found,
            count=len(found),
            truncated=truncated,
            scanned_files=scanned,
        )

    def _open_folder(self, requested: str) -> dict:
        label = " ".join(str(requested or "").strip().lower().split())
        if label == "recycle bin":
            try:
                self._process_launcher(["explorer.exe", "shell:RecycleBinFolder"])
            except (OSError, subprocess.SubprocessError) as exc:
                return self._failed("start", "Windows could not open the Recycle Bin.", result={"error_type": type(exc).__name__})
            return self._succeed("start", "Opened Recycle Bin", operation="open_folder", folder="Recycle Bin")
        if label in {"this pc", "my computer", "computer"}:
            try:
                self._process_launcher(["explorer.exe", "shell:MyComputerFolder"])
            except (OSError, subprocess.SubprocessError) as exc:
                return self._failed("start", "Windows could not open This PC.", result={"error_type": type(exc).__name__})
            return self._succeed("start", "Opened This PC", operation="open_folder", folder="This PC")
        drive_root = self.DRIVE_ROOTS.get(label)
        folder_name = self.FOLDER_NAMES.get(label)
        if drive_root is None and not folder_name:
            return self._failed("start", "Only standard user folders or the allowlisted Local Disk C root can be opened.")
        folder = drive_root if drive_root is not None else self.home_directory / str(folder_name)
        display_name = "Local Disk C" if drive_root is not None else str(folder_name)
        if not folder.is_dir():
            return self._failed("start", f"The {display_name} folder is not available.")
        try:
            self._file_opener(str(folder))
        except (OSError, subprocess.SubprocessError):
            return self._failed("start", f"NOVA could not open {display_name}.")
        return self._succeed("start", f"Opened {display_name}", operation="open_folder", folder=display_name)

    def _open_file(self, requested: str) -> dict:
        name = str(requested or "").strip()
        if not name or len(name) > 180 or "/" in name or "\\" in name or name in {".", ".."}:
            return self._failed("start", "Provide an exact file name, not a file path.")
        matches_result = self._find_files(name)
        if not matches_result.get("success"):
            return self._failed("start", str(matches_result.get("error") or "File search failed."))
        requested_has_extension = bool(Path(name).suffix)
        candidates = [
            item for item in matches_result["result"]["files"]
            if item["name"].casefold() == name.casefold()
            or (
                not requested_has_extension
                and Path(item["name"]).stem.casefold() == name.casefold()
            )
        ]
        if not candidates:
            return self._failed("start", f"No file named '{name}' was found in the standard user folders.")
        if len(candidates) > 1:
            return self._failed(
                "start",
                "More than one file has that exact name; search first and choose the intended location.",
                result={"matches": [{"name": item["name"], "path": item["path"]} for item in candidates]},
            )
        chosen = candidates[0]
        if chosen["extension"] not in self.SAFE_OPEN_EXTENSIONS:
            return self._failed(
                "start",
                "For safety, NOVA won't launch executable or script files from a voice command.",
                result={"name": chosen["name"], "extension": chosen["extension"]},
            )
        try:
            self._file_opener(chosen["path"])
        except (OSError, subprocess.SubprocessError):
            return self._failed("start", f"NOVA found '{name}' but could not open it.")
        # Audit/UI output contains the basename, not the full private local path.
        return self._succeed("start", f"Opened {chosen['name']}", operation="open_file", file_name=chosen["name"])
