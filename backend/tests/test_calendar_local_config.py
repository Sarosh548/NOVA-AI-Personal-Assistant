from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _read_root_file(name: str) -> str:
    return (
        REPOSITORY_ROOT
        / name
    ).read_text(
        encoding="utf-8"
    )


def test_local_env_example_documents_google_calendar_configuration():
    content = _read_root_file(
        ".env.example"
    )

    expected_lines = (
        "CALENDAR_GOOGLE_CLIENT_ID=",
        "CALENDAR_GOOGLE_CLIENT_SECRET=",
        "CALENDAR_GOOGLE_REDIRECT_URI=http://localhost:8000/integrations/google/calendar/callback",
        "CALENDAR_GOOGLE_SCOPES=https://www.googleapis.com/auth/calendar.events",
    )

    for line in expected_lines:
        assert line in content


def test_local_compose_passes_google_calendar_configuration_to_backend():
    content = _read_root_file(
        "docker-compose.local.yml"
    )

    expected_lines = (
        "CALENDAR_GOOGLE_CLIENT_ID: ${CALENDAR_GOOGLE_CLIENT_ID:-}",
        "CALENDAR_GOOGLE_CLIENT_SECRET: ${CALENDAR_GOOGLE_CLIENT_SECRET:-}",
        "CALENDAR_GOOGLE_REDIRECT_URI: ${CALENDAR_GOOGLE_REDIRECT_URI:-http://localhost:8000/integrations/google/calendar/callback}",
        "CALENDAR_GOOGLE_SCOPES: ${CALENDAR_GOOGLE_SCOPES:-https://www.googleapis.com/auth/calendar.events}",
    )

    for line in expected_lines:
        assert line in content
