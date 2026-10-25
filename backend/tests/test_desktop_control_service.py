from __future__ import annotations

from pathlib import Path

from services.desktop_control_service import DesktopControlService


def make_service(
    tmp_path: Path,
    *,
    process_launcher=None,
    url_opener=None,
    file_opener=None,
    enabled: bool = True,
) -> DesktopControlService:
    return DesktopControlService(
        enabled=enabled,
        platform_name="nt",
        home_directory=tmp_path,
        process_launcher=process_launcher or (lambda command: None),
        url_opener=url_opener or (lambda url: True),
        file_opener=file_opener or (lambda path: None),
    )


class _FakeElementInfo:
    def __init__(self, name, control_type):
        self.name = name
        self.control_type = control_type


class _FakeControl:
    def __init__(self, name, control_type):
        self.element_info = _FakeElementInfo(name, control_type)
        self.clicked = 0
        self.value = None
        self.focused = False

    def is_enabled(self):
        return True

    def is_visible(self):
        return True

    def window_text(self):
        return self.element_info.name

    def click_input(self):
        self.clicked += 1

    def set_edit_text(self, value):
        self.value = value

    def set_focus(self):
        self.focused = True

    def descendants(self):
        return []

    def children(self):
        return []


class _FakeWindow(_FakeControl):
    def __init__(self, title, controls):
        super().__init__(title, "Window")
        self._controls = controls

    def descendants(self):
        return self._controls

    def children(self):
        return self._controls


class _FakeDesktop:
    def __init__(self, windows):
        self._windows = windows

    def windows(self, **kwargs):
        return self._windows


class _FakeBrowserWindow(_FakeWindow):
    def __init__(self, title, controls):
        super().__init__(title, controls)
        self.current_title = title

    def window_text(self):
        return self.current_title


def test_play_youtube_selects_matching_result_and_verifies_playback(tmp_path, monkeypatch):
    search_field = _FakeControl("Search", "Edit")
    video_link = _FakeControl("Interstellar Soundtrack - Official Video", "Hyperlink")
    window = _FakeBrowserWindow("Interstellar - YouTube - Opera", [search_field, video_link])
    clicked_urls = []

    def start_video():
        video_link.clicked += 1
        window.current_title = "Interstellar Soundtrack - YouTube - Opera"
        window._controls = [_FakeControl("Pause (k)", "Button")]

    video_link.click_input = start_video
    service = make_service(tmp_path)
    monkeypatch.setattr(service, "_open_url", lambda url: clicked_urls.append(url) or {
        "success": True, "tool": "desktop", "action": "start",
        "result": {"operation": "open_url", "url": url}, "error": None,
    })
    monkeypatch.setattr(service, "_uia_desktop", lambda: _FakeDesktop([window]))

    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "play_youtube", "desktop_target": "Interstellar Soundtrack"},
    )

    assert result["success"] is True
    assert result["result"]["playback_verified"] is True
    assert result["result"]["operation"] == "play_youtube"
    assert result["result"]["video_title"] == "Interstellar Soundtrack - Official Video"
    assert clicked_urls == [
        "https://www.youtube.com/results?search_query=Interstellar+Soundtrack"
    ]
    assert video_link.clicked == 1


def test_play_youtube_verifies_repeated_title_terms_using_distinct_tokens(tmp_path, monkeypatch):
    video_link = _FakeControl("Pal Pal Official Audio", "Hyperlink")
    window = _FakeBrowserWindow("YouTube - Opera", [video_link])

    def start_video():
        video_link.clicked += 1
        # Some browsers omit "Official Audio" from the window title even when
        # the matching result is selected and the player is observably playing.
        window.current_title = "Pal Pal - YouTube - Opera"
        window._controls = [_FakeControl("Pause (k)", "Button")]

    video_link.click_input = start_video
    service = make_service(tmp_path)
    monkeypatch.setattr(service, "_open_url", lambda url: {
        "success": True,
        "tool": "desktop",
        "action": "start",
        "result": {"operation": "open_url", "url": url},
        "error": None,
    })
    monkeypatch.setattr(service, "_uia_desktop", lambda: _FakeDesktop([window]))

    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "play_youtube", "desktop_target": "Pal Pal"},
    )

    assert result["success"] is True
    assert result["result"]["playback_verified"] is True
    assert result["result"]["video_title"] == "Pal Pal Official Audio"
    assert video_link.clicked == 1


def test_play_youtube_selects_latest_video_adjacent_to_requested_creator(tmp_path, monkeypatch):
    inactive_tab = _FakeControl(
        "(167) MrBeast ki koi latest video - YouTube",
        "TabItem",
    )
    youtube_home_tab = _FakeControl("(167) YouTube", "TabItem")
    unrelated_video = _FakeControl("Celebrity drama clip 1 day ago", "Hyperlink")
    unrelated_channel = _FakeControl("Go to channel Reaction Channel", "Hyperlink")
    latest_creator_video = _FakeControl(
        "Last To Leave Mansion, Keeps It 57 minutes",
        "Hyperlink",
    )
    creator_channel = _FakeControl("Go to channel MrBeast", "Hyperlink")
    window = _FakeBrowserWindow(
        "YouTube - Opera",
        [
            inactive_tab,
            youtube_home_tab,
            unrelated_video,
            unrelated_channel,
            latest_creator_video,
            creator_channel,
        ],
    )
    clicked_urls = []

    def activate_results_tab():
        inactive_tab.clicked += 1
        window.current_title = "MrBeast ki koi latest video - YouTube - Opera"

    inactive_tab.click_input = activate_results_tab

    def start_video():
        latest_creator_video.clicked += 1
        window.current_title = "Last To Leave Mansion, Keeps It - YouTube - Opera"
        window._controls = [_FakeControl("Pause (k)", "Button")]

    latest_creator_video.click_input = start_video
    service = make_service(tmp_path)
    monkeypatch.setattr(service, "_open_url", lambda url: clicked_urls.append(url) or {
        "success": True,
        "tool": "desktop",
        "action": "start",
        "result": {"operation": "open_url", "url": url},
        "error": None,
    })
    monkeypatch.setattr(service, "_uia_desktop", lambda: _FakeDesktop([window]))

    result = service.execute(
        user_id="user-1",
        action="start",
        data={
            "desktop_operation": "play_youtube",
            "desktop_target": "MrBeast ki koi latest video",
        },
    )

    assert result["success"] is True
    assert result["result"]["playback_verified"] is True
    assert result["result"]["video_title"] == "Last To Leave Mansion, Keeps It 57 minutes"
    assert inactive_tab.clicked == 1
    assert latest_creator_video.clicked == 1
    assert clicked_urls == [
        "https://www.youtube.com/results?search_query=MrBeast+ki+koi+latest+video&sp=CAI%3D"
    ]


def test_play_youtube_rejects_vague_song_request_without_opening_browser(tmp_path, monkeypatch):
    opened = []
    service = make_service(tmp_path)
    monkeypatch.setattr(service, "_open_url", lambda url: opened.append(url) or True)

    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "play_youtube", "desktop_target": "song"},
    )

    assert result["success"] is False
    assert "specific" in result["error"].lower()
    assert opened == []


def test_ui_automation_prioritizes_page_controls_over_browser_chrome(tmp_path, monkeypatch):
    window = _FakeBrowserWindow(
        "YouTube - Opera",
        [
            _FakeControl("Minimize", "Button"),
            _FakeControl("Address bar", "Edit"),
            _FakeControl("Play", "Button"),
            _FakeControl("Search", "Edit"),
            _FakeControl("Video title: Interstellar", "Text"),
        ],
    )
    service = make_service(tmp_path)
    monkeypatch.setattr(service, "_uia_desktop", lambda: _FakeDesktop([window]))

    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "inspect_screen", "desktop_target": ""},
    )

    assert result["success"] is True
    controls = result["result"]["windows"][0]["controls"]
    assert controls[0]["name"] == "Address bar"
    assert controls[1]["name"] == "Search"
    assert controls[2]["name"] == "Play"
    assert controls[-1]["name"] == "Minimize"


def test_ui_automation_activates_unique_inactive_browser_tab_for_targeted_click(tmp_path, monkeypatch):
    youtube_tab = _FakeControl("(166) YouTube", "TabItem")
    play_button = _FakeControl("Play", "Button")
    window = _FakeBrowserWindow("NOVA Par Kaam - Opera", [youtube_tab, play_button])

    def activate_youtube_tab():
        youtube_tab.clicked += 1
        window.current_title = "YouTube - Opera"

    youtube_tab.click_input = activate_youtube_tab
    service = make_service(tmp_path)
    monkeypatch.setattr(service, "_uia_desktop", lambda: _FakeDesktop([window]))

    result = service.execute(
        user_id="user-1",
        action="start",
        data={
            "desktop_operation": "click_ui",
            "desktop_target": "Play",
            "desktop_query": "YouTube",
        },
    )

    assert result["success"] is True
    assert result["result"]["window_title"] == "YouTube - Opera"
    assert youtube_tab.clicked == 1
    assert play_button.clicked == 1


def test_ui_automation_inspects_and_clicks_unique_safe_control(tmp_path, monkeypatch):
    search_button = _FakeControl("Search", "Button")
    status_text = _FakeControl("Inbox has 2 unread messages", "Text")
    window = _FakeWindow("YouTube - Opera", [search_button, status_text])
    service = make_service(tmp_path)
    monkeypatch.setattr(service, "_uia_desktop", lambda: _FakeDesktop([window]))

    inspected = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "inspect_screen", "desktop_target": ""},
    )
    assert inspected["success"] is True
    names = {item["name"] for item in inspected["result"]["windows"][0]["controls"]}
    assert "Search" in names
    assert "Inbox has 2 unread messages" in names

    clicked = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "click_ui", "desktop_target": "Search", "desktop_query": "YouTube"},
    )
    assert clicked["success"] is True
    assert clicked["result"]["control_name"] == "Search"
    assert search_button.clicked == 1

    blocked = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "click_ui", "desktop_target": "Send now", "desktop_query": "YouTube"},
    )
    assert blocked["success"] is False
    assert search_button.clicked == 1

    for dangerous_label in (
        "Forward message", "Archive", "Move to trash", "Mark as spam",
        "Like this video", "Follow creator", "Subscribe", "Post comment",
    ):
        rejected = service.execute(
            user_id="user-1",
            action="start",
            data={
                "desktop_operation": "click_ui",
                "desktop_target": dangerous_label,
                "desktop_query": "YouTube",
            },
        )
        assert rejected["success"] is False, dangerous_label
    assert search_button.clicked == 1


def test_ui_automation_refuses_to_click_through_os_security_prompts(tmp_path, monkeypatch):
    yes_button = _FakeControl("Yes", "Button")
    uac_window = _FakeWindow("User Account Control", [yes_button])
    service = make_service(tmp_path)
    monkeypatch.setattr(service, "_uia_desktop", lambda: _FakeDesktop([uac_window]))

    result = service.execute(
        user_id="user-1",
        action="start",
        data={
            "desktop_operation": "click_ui",
            "desktop_target": "Yes",
            "desktop_query": "User Account Control",
        },
    )
    assert result["success"] is False
    assert "security" in result["error"].lower()
    assert yes_button.clicked == 0


def test_ui_automation_resolves_text_field_by_app_context(tmp_path, monkeypatch):
    taskbar_search = _FakeControl("Search", "Edit")
    youtube_search = _FakeControl("Search", "Edit")
    taskbar = _FakeWindow("Taskbar", [taskbar_search])
    browser = _FakeWindow("YouTube - Opera", [youtube_search])
    service = make_service(tmp_path)
    monkeypatch.setattr(service, "_uia_desktop", lambda: _FakeDesktop([taskbar, browser]))

    result = service.execute(
        user_id="user-1",
        action="start",
        data={
            "desktop_operation": "type_ui",
            "desktop_target": "Search bar in YouTube",
            "desktop_query": "Interstellar",
        },
    )
    assert result["success"] is True
    assert taskbar_search.value is None
    assert youtube_search.value == "Interstellar"


def test_enter_and_space_are_blocked_in_email_and_social_tabs(tmp_path, monkeypatch):
    for title, key in (("Gmail - Opera", "enter"), ("YouTube - Opera", "space")):
        window = _FakeWindow(title, [])
        service = make_service(tmp_path)
        monkeypatch.setattr(service, "_uia_desktop", lambda window=window: _FakeDesktop([window]))

        result = service.execute(
            user_id="user-1",
            action="start",
            data={
                "desktop_operation": "press_key",
                "desktop_target": key,
                "desktop_query": "Opera",
            },
        )
        assert result["success"] is False, title
        assert "blocked" in result["error"].lower(), title


def test_ui_automation_types_only_into_unique_non_sensitive_field(tmp_path, monkeypatch):
    search_field = _FakeControl("Search", "Edit")
    password_field = _FakeControl("Password", "Edit")
    window = _FakeWindow("YouTube - Opera", [search_field, password_field])
    service = make_service(tmp_path)
    monkeypatch.setattr(service, "_uia_desktop", lambda: _FakeDesktop([window]))

    typed = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "type_ui", "desktop_target": "Search", "desktop_query": "Interstellar"},
    )
    assert typed["success"] is True
    assert search_field.value == "Interstellar"
    assert typed["result"]["character_count"] == len("Interstellar")

    rejected = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "type_ui", "desktop_target": "Password", "desktop_query": "not-a-real-password"},
    )
    assert rejected["success"] is False
    assert password_field.value is None


def test_desktop_control_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("NOVA_DESKTOP_CONTROL_ENABLED", raising=False)
    service = DesktopControlService(platform_name="nt", home_directory=tmp_path)

    assert service.is_available is False
    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_app", "desktop_target": "notepad"},
    )
    assert result["success"] is False
    assert "disabled" in result["error"].lower()


def test_desktop_control_refuses_non_windows_platform_even_when_enabled(tmp_path):
    service = DesktopControlService(
        enabled=True,
        platform_name="posix",
        environment="development",
        home_directory=tmp_path,
    )
    assert service.is_available is False


def test_desktop_control_is_never_available_in_production(tmp_path):
    service = DesktopControlService(
        enabled=True,
        platform_name="nt",
        environment="production",
        home_directory=tmp_path,
    )
    assert service.is_available is False


def test_open_app_launches_only_an_allowlisted_application(tmp_path):
    launched = []
    service = make_service(tmp_path, process_launcher=lambda command: launched.append(command))

    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_app", "desktop_target": "Notepad"},
    )

    assert result["success"] is True
    assert launched == [["notepad.exe"]]
    assert result["result"]["application"] == "notepad"


def test_open_app_rejects_arbitrary_commands_and_shells(tmp_path):
    launched = []
    service = make_service(tmp_path, process_launcher=lambda command: launched.append(command))

    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_app", "desktop_target": "powershell -Command whoami"},
    )

    assert result["success"] is False
    assert launched == []
    assert "allowlist" in result["error"].lower()


def test_open_app_launches_exact_unknown_start_menu_shortcut(tmp_path, monkeypatch):
    app_data = tmp_path / "user"
    program_data = tmp_path / "common"
    shortcut = (
        app_data / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Spotify.lnk"
    )
    shortcut.parent.mkdir(parents=True)
    shortcut.write_bytes(b"mock shortcut")
    monkeypatch.setenv("APPDATA", str(app_data))
    monkeypatch.setenv("PROGRAMDATA", str(program_data))

    opened = []
    service = make_service(tmp_path, file_opener=lambda path: opened.append(path))
    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_app", "desktop_target": "Spotify"},
    )

    assert result["success"] is True
    assert opened == [str(shortcut)]
    assert result["result"]["application"] == "Spotify"
    assert result["result"]["launch_source"] == "start_menu"


def test_open_app_rejects_ambiguous_start_menu_shortcuts(tmp_path, monkeypatch):
    app_data = tmp_path / "user"
    program_data = tmp_path / "common"
    user_shortcut = (
        app_data / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "AppName.lnk"
    )
    common_shortcut = (
        program_data / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "AppName.lnk"
    )
    user_shortcut.parent.mkdir(parents=True)
    common_shortcut.parent.mkdir(parents=True)
    user_shortcut.write_bytes(b"user shortcut")
    common_shortcut.write_bytes(b"common shortcut")
    monkeypatch.setenv("APPDATA", str(app_data))
    monkeypatch.setenv("PROGRAMDATA", str(program_data))

    opened = []
    service = make_service(tmp_path, file_opener=lambda path: opened.append(path))
    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_app", "desktop_target": "AppName"},
    )

    assert result["success"] is False
    assert "more than one" in result["error"].lower()
    assert opened == []


def test_open_url_only_accepts_http_and_https_without_embedded_credentials(tmp_path):
    opened = []
    service = make_service(tmp_path, url_opener=lambda url: opened.append(url) or True)

    good = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_url", "desktop_target": "https://example.com/path"},
    )
    bad_scheme = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_url", "desktop_target": "file:///C:/Windows/win.ini"},
    )
    bad_credentials = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_url", "desktop_target": "https://user:secret@example.com"},
    )

    assert good["success"] is True
    assert opened == ["https://example.com/path"]
    assert bad_scheme["success"] is False
    assert bad_credentials["success"] is False


def test_search_files_is_limited_to_standard_user_folders(tmp_path):
    docs = tmp_path / "Documents"
    downloads = tmp_path / "Downloads"
    outside = tmp_path / "private"
    docs.mkdir()
    downloads.mkdir()
    outside.mkdir()
    (docs / "NOVA-plan.pdf").write_text("plan", encoding="utf-8")
    (downloads / "nova-notes.txt").write_text("notes", encoding="utf-8")
    (outside / "nova-private.txt").write_text("private", encoding="utf-8")
    service = make_service(tmp_path)

    result = service.execute(
        user_id="user-1",
        action="search",
        data={"desktop_operation": "find_files", "desktop_query": "nova"},
    )

    assert result["success"] is True
    paths = [item["path"] for item in result["result"]["files"]]
    assert len(paths) == 2
    assert all(str(docs) in path or str(downloads) in path for path in paths)
    assert all(str(outside) not in path for path in paths)


def test_cv_file_search_matches_cv_and_resume_filename_aliases(tmp_path):
    docs = tmp_path / "Documents"
    downloads = tmp_path / "Downloads"
    docs.mkdir()
    downloads.mkdir()
    (docs / "Sarosh_CV.pdf").write_bytes(b"%PDF-cv")
    (downloads / "Sarosh_Qaiser_AI_Engineer_Resume.docx").write_bytes(b"resume")
    onedrive = tmp_path / "OneDrive" / "Career"
    onedrive.mkdir(parents=True)
    (onedrive / "Sarosh_AI_CV_v2.pdf").write_bytes(b"%PDF-onedrive")
    (docs / "Curriculum.Vitae.txt").write_text("curriculum vitae", encoding="utf-8")
    (docs / "cv.dat").write_bytes(b"locale data")
    (docs / "msvcp140_codecvt_ids.dll").write_bytes(b"library")
    (downloads / "cv2.pyd").write_bytes(b"python extension")
    hidden = tmp_path / ".private"
    hidden.mkdir()
    (hidden / "secret-CV.pdf").write_bytes(b"hidden")
    (downloads / "notes.txt").write_text("not a CV", encoding="utf-8")
    service = make_service(tmp_path)

    result = service.execute(
        user_id="user-1",
        action="search",
        data={"desktop_operation": "find_files", "desktop_query": "cv"},
    )

    assert result["success"] is True
    names = {item["name"] for item in result["result"]["files"]}
    assert names == {
        "Sarosh_CV.pdf",
        "Sarosh_Qaiser_AI_Engineer_Resume.docx",
        "Sarosh_AI_CV_v2.pdf",
        "Curriculum.Vitae.txt",
    }


def test_open_local_disk_c_uses_only_the_allowlisted_root(tmp_path, monkeypatch):
    opened = []
    service = make_service(tmp_path, file_opener=lambda path: opened.append(path))
    original_is_dir = Path.is_dir

    def fake_is_dir(path):
        if str(path).replace("\\\\", "/").casefold().rstrip("/") == "c:":
            return True
        return original_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)
    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_folder", "desktop_target": "local disk c"},
    )

    assert result["success"] is True
    assert result["result"]["folder"] == "Local Disk C"
    assert opened == [str(service.DRIVE_ROOTS["local disk c"])]

    spoken_alias = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_folder", "desktop_target": "local drive c"},
    )
    assert spoken_alias["success"] is True
    assert spoken_alias["result"]["folder"] == "Local Disk C"
    assert opened[-1] == str(service.DRIVE_ROOTS["local drive c"])

    rejected = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_folder", "desktop_target": "C:\\\\Windows"},
    )
    assert rejected["success"] is False


def test_open_file_without_extension_resolves_a_unique_safe_basename(tmp_path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "World.docx").write_bytes(b"docx")
    opened = []
    service = make_service(tmp_path, file_opener=lambda path: opened.append(path))

    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_file", "desktop_target": "World"},
    )

    assert result["success"] is True
    assert result["result"]["file_name"] == "World.docx"
    assert opened == [str(docs / "World.docx")]


def test_open_file_rejects_scripts_and_opens_supported_documents(tmp_path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "brief.pdf").write_bytes(b"%PDF-test")
    (docs / "run-me.ps1").write_text("Write-Host unsafe", encoding="utf-8")
    opened = []
    service = make_service(tmp_path, file_opener=lambda path: opened.append(path))

    safe = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_file", "desktop_target": "brief.pdf"},
    )
    unsafe = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_file", "desktop_target": "run-me.ps1"},
    )

    assert safe["success"] is True
    assert safe["result"]["file_name"] == "brief.pdf"
    assert unsafe["success"] is False
    assert "executable" in unsafe["error"].lower() or "script" in unsafe["error"].lower()
    assert opened == [str(docs / "brief.pdf")]


def test_open_file_does_not_guess_between_duplicate_names(tmp_path):
    docs = tmp_path / "Documents"
    downloads = tmp_path / "Downloads"
    docs.mkdir()
    downloads.mkdir()
    (docs / "proposal.pdf").write_bytes(b"%PDF-a")
    (downloads / "proposal.pdf").write_bytes(b"%PDF-b")
    opened = []
    service = make_service(tmp_path, file_opener=lambda path: opened.append(path))

    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_file", "desktop_target": "proposal.pdf"},
    )

    assert result["success"] is False
    assert "more than one" in result["error"].lower()
    assert opened == []


def test_list_recent_downloads_includes_metadata_and_marks_partial_downloads(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    older = downloads / "older-report.pdf"
    newer = downloads / "new-video.mp4.crdownload"
    older.write_bytes(b"pdf-report")
    newer.write_bytes(b"partial-download")
    import os
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))

    service = make_service(tmp_path)
    result = service.execute(
        user_id="user-1",
        action="search",
        data={"desktop_operation": "list_files", "desktop_query": "downloads"},
    )

    assert result["success"] is True
    assert result["result"]["folder"] == "Downloads"
    assert result["result"]["count"] == 2
    assert result["result"]["files"][0]["name"] == "new-video.mp4.crdownload"
    assert result["result"]["files"][0]["incomplete_download"] is True
    assert result["result"]["files"][1]["name"] == "older-report.pdf"
    assert result["result"]["files"][1]["incomplete_download"] is False
    assert "path" in result["result"]["files"][0]


def test_list_files_rejects_paths_and_non_allowlisted_folders(tmp_path):
    service = make_service(tmp_path)
    for query in ("../Documents", "C:\\\\", "AppData"):
        result = service.execute(
            user_id="user-1",
            action="search",
            data={"desktop_operation": "list_files", "desktop_query": query},
        )
        assert result["success"] is False


def test_this_pc_opens_only_the_fixed_shell_namespace(tmp_path):
    launched = []
    service = make_service(tmp_path, process_launcher=lambda command: launched.append(command))
    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_folder", "desktop_target": "this pc"},
    )
    assert result["success"] is True
    assert result["result"]["folder"] == "This PC"
    assert launched == [["explorer.exe", "shell:MyComputerFolder"]]


def test_recycle_bin_opens_only_the_fixed_shell_namespace(tmp_path):
    launched = []
    service = make_service(tmp_path, process_launcher=lambda command: launched.append(command))
    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_folder", "desktop_target": "recycle bin"},
    )
    assert result["success"] is True
    assert result["result"]["folder"] == "Recycle Bin"
    assert launched == [["explorer.exe", "shell:RecycleBinFolder"]]


def test_microsoft_store_uses_its_known_windows_app_id(tmp_path):
    launched = []
    service = make_service(tmp_path, process_launcher=lambda command: launched.append(command))
    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_app", "desktop_target": "microsoft store"},
    )
    assert result["success"] is True
    assert launched == [[
        "explorer.exe",
        r"shell:AppsFolder\Microsoft.WindowsStore_8wekyb3d8bbwe!App",
    ]]


def test_open_spotify_falls_back_to_web_player_only_when_native_app_is_missing(tmp_path, monkeypatch):
    user_start = tmp_path / "user"
    common_start = tmp_path / "common"
    user_start.mkdir()
    common_start.mkdir()
    monkeypatch.setenv("APPDATA", str(user_start))
    monkeypatch.setenv("PROGRAMDATA", str(common_start))
    opened_urls = []
    service = make_service(tmp_path, url_opener=lambda url: opened_urls.append(url) or True)

    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_app", "desktop_target": "spotify"},
    )

    assert result["success"] is True
    assert result["result"]["application"] == "Spotify Web Player"
    assert result["result"]["launch_source"] == "browser_fallback"
    assert opened_urls == ["https://open.spotify.com/"]


def test_play_spotify_selects_matching_track_and_verifies_playback(tmp_path, monkeypatch):
    play_button = _FakeControl("Play Pal Pal", "Button")
    window = _FakeBrowserWindow("Pal Pal - Spotify - Opera", [play_button])
    opened_urls = []

    def start_playback():
        play_button.clicked += 1
        window.current_title = "Pal Pal - Spotify - Opera"
        window._controls = [_FakeControl("Pause (k)", "Button")]

    play_button.click_input = start_playback
    service = make_service(tmp_path)
    monkeypatch.setattr(service, "_open_url", lambda url: opened_urls.append(url) or {
        "success": True,
        "tool": "desktop",
        "action": "start",
        "result": {"operation": "open_url", "url": url},
        "error": None,
    })
    monkeypatch.setattr(service, "_uia_desktop", lambda: _FakeDesktop([window]))

    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "play_spotify", "desktop_target": "Pal Pal"},
    )

    assert result["success"] is True
    assert result["result"]["operation"] == "play_spotify"
    assert result["result"]["playback_verified"] is True
    assert result["result"]["track_title"] == "Pal Pal"
    assert play_button.clicked == 1
    assert opened_urls == ["https://open.spotify.com/search/Pal+Pal"]


def test_web_search_opens_a_url_escaped_query(tmp_path):
    opened = []
    service = make_service(tmp_path, url_opener=lambda url: opened.append(url) or True)

    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "search_web", "desktop_target": "NOVA AI & voice"},
    )

    assert result["success"] is True
    assert result["result"]["query"] == "NOVA AI & voice"
    assert opened == ["https://www.google.com/search?q=NOVA+AI+%26+voice"]



def test_open_app_supports_allowlisted_office_app(tmp_path):
    launched = []
    service = make_service(tmp_path, process_launcher=lambda command: launched.append(command))
    service._office_candidates = lambda application: [[application + ".EXE"]]

    result = service.execute(
        user_id="user-1",
        action="start",
        data={"desktop_operation": "open_app", "desktop_target": "Outlook"},
    )

    assert result["success"] is True
    assert result["result"]["application"] == "outlook"
    assert launched == [["outlook.EXE"]]
