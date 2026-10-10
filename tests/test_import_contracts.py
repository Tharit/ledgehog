"""The architecture's boundary rules (§5.1) are enforced by import-linter; here we prove the
contracts pass on the tree and that each kind of violation actually fails them."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUN = "from importlinter.cli import lint_imports_command; lint_imports_command()"


def lint(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", RUN], cwd=cwd, capture_output=True, text=True, timeout=120)


def test_contracts_pass_on_the_real_tree():
    result = lint(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "KEPT" in result.stdout and "BROKEN" not in result.stdout


@pytest.fixture
def project(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "app", tmp_path / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / ".importlinter", tmp_path / ".importlinter")
    return tmp_path


VIOLATIONS = {
    "core imports a concrete plugin": ("app/core/ingest/bad.py", "import app.plugins.importers\n"),
    "core imports api": ("app/core/ingest/bad.py", "import app.api\n"),
    "core imports a web framework": ("app/core/ingest/bad.py", "import fastapi\n"),
    "core reads configuration itself": ("app/core/ingest/bad.py", "import app.utils.config\n"),
    "domain imports another core package": ("app/core/domain/bad.py", "import app.core.ingest\n"),
    "domain imports utils": ("app/core/domain/bad.py", "import app.utils.clock\n"),
    "plugin imports api": ("app/plugins/importers/bad.py", "import app.api\n"),
    "plugin imports the db layer": ("app/plugins/importers/bad.py", "import app.utils.db.engine\n"),
    "utils imports core": ("app/utils/bad.py", "import app.core.domain.money\n"),
    "api imports a concrete plugin": ("app/api/bad.py", "import app.plugins.importers\n"),
    "utils imports a web framework": ("app/utils/auth/bad.py", "import fastapi\n"),
}


@pytest.mark.parametrize("name", VIOLATIONS)
def test_violation_fails_the_contracts(project: Path, name: str):
    rel, content = VIOLATIONS[name]
    (project / rel).write_text(content)
    result = lint(project)
    assert result.returncode != 0, f"{name} was not caught:\n{result.stdout}"
    assert "BROKEN" in result.stdout
