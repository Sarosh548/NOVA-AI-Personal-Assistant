from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_reranker_service_import_does_not_load_sentence_transformers():
    backend_dir = Path(__file__).resolve().parents[1]
    script = (
        "import sys; "
        "from services.reranker_service import RerankerService; "
        "service = RerankerService(); "
        "assert service._model is None; "
        "assert 'sentence_transformers' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
