import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ["SENTINEL_DATA_DIR"] = tempfile.mkdtemp(prefix="sentinel_test_")
os.environ.pop("OPENAI_API_KEY", None)

import pytest  # noqa: E402

from config import SAMPLE_DIR  # noqa: E402


@pytest.fixture(scope="session")
def sample_dir() -> Path:
    if not SAMPLE_DIR.exists() or not any(SAMPLE_DIR.iterdir()):
        from sample_data.generate_samples import main

        main()
    return SAMPLE_DIR


@pytest.fixture(scope="session")
def parsed_docs(sample_dir):
    from documents.pipeline import parse_file
    from documents.security import validate_file

    return [parse_file(p, f"file{i}", p.name, validate_file(p, p.name)) for i, p in enumerate(sorted(sample_dir.iterdir()))]


@pytest.fixture()
def extraction(parsed_docs):
    from documents.pipeline import extract_all

    return extract_all(parsed_docs)
