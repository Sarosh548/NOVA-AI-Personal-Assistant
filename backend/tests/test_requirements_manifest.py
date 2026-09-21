from pathlib import Path


REQUIRED_RUNTIME_DISTRIBUTIONS = {
    "alembic",
    "cryptography",
    "fastapi",
    "langgraph",
    "openai",
    "pgvector",
    "psycopg",
    "pydantic",
    "pydantic-settings",
    "pypdf",
    "pwdlib",
    "python-docx",
    "python-multipart",
    "sentence-transformers",
    "SQLAlchemy",
    "uvicorn",
}


def _requirement_names() -> set[str]:
    requirements_path = (
        Path(__file__).resolve().parents[2]
        / "requirements.txt"
    )

    names: set[str] = set()

    for raw_line in requirements_path.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        distribution = line.split("==", 1)[0].strip()

        if "[" in distribution:
            distribution = distribution.split(
                "[",
                1,
            )[0]

        names.add(distribution)

    return names


def test_runtime_dependencies_are_declared():
    declared = _requirement_names()

    missing = (
        REQUIRED_RUNTIME_DISTRIBUTIONS
        - declared
    )

    assert missing == set()
