import plistlib

from tradalgo.cli import LAUNCHD_PLISTS, render_launchd_plists


def test_render_launchd_plists_parse_and_use_absolute_paths(tmp_path):
    repo = tmp_path / "repo"
    python_path = repo / ".venv" / "bin" / "python"
    rendered = render_launchd_plists(repo, python_path)

    assert set(rendered) == set(LAUNCHD_PLISTS)
    for name, content in rendered.items():
        data = plistlib.loads(content.encode())
        assert data["WorkingDirectory"] == str(repo)
        assert str(python_path) in data["ProgramArguments"]
        assert str(repo / "data" / "logs") in data["StandardOutPath"]
        assert "{{" not in content


def test_screen_schedule_is_weekdays_at_0700(tmp_path):
    rendered = render_launchd_plists(tmp_path / "repo", tmp_path / "repo" / ".venv" / "bin" / "python")
    data = plistlib.loads(rendered["com.tradalgo.screen.plist"].encode())
    intervals = data["StartCalendarInterval"]
    assert {i["Weekday"] for i in intervals} == {1, 2, 3, 4, 5}
    assert all(i["Hour"] == 7 and i["Minute"] == 0 for i in intervals)


def test_preopen_schedule_is_weekdays_at_0908(tmp_path):
    rendered = render_launchd_plists(tmp_path / "repo", tmp_path / "repo" / ".venv" / "bin" / "python")
    data = plistlib.loads(rendered["com.tradalgo.preopen.plist"].encode())
    intervals = data["StartCalendarInterval"]
    assert {i["Weekday"] for i in intervals} == {1, 2, 3, 4, 5}
    assert all(i["Hour"] == 9 and i["Minute"] == 8 for i in intervals)


def test_session_schedule_is_weekdays_at_0900(tmp_path):
    rendered = render_launchd_plists(tmp_path / "repo", tmp_path / "repo" / ".venv" / "bin" / "python")
    data = plistlib.loads(rendered["com.tradalgo.session.plist"].encode())
    intervals = data["StartCalendarInterval"]
    assert {i["Weekday"] for i in intervals} == {1, 2, 3, 4, 5}
    assert all(i["Hour"] == 9 and i["Minute"] == 0 for i in intervals)


def test_worker_and_dashboard_run_at_load_and_keepalive(tmp_path):
    rendered = render_launchd_plists(tmp_path / "repo", tmp_path / "repo" / ".venv" / "bin" / "python")
    for name in ("com.tradalgo.worker.plist", "com.tradalgo.dashboard.plist"):
        data = plistlib.loads(rendered[name].encode())
        assert data["RunAtLoad"] is True
        assert data["KeepAlive"] is True


def test_dashboard_runs_tradalgo_dashboard_command(tmp_path):
    rendered = render_launchd_plists(tmp_path / "repo", tmp_path / "repo" / ".venv" / "bin" / "python")
    data = plistlib.loads(rendered["com.tradalgo.dashboard.plist"].encode())
    assert data["ProgramArguments"][-1] == "dashboard"
