"""Guards against dependency drift.

`app/agent/model.py` imports each provider's package lazily, inside the branch
that uses it, so a missing dependency does not fail at import time or at boot —
it fails when a job actually runs, in whichever environment happens to select
that provider. `MODEL_PROVIDER` defaults to `bedrock` on AWS and `ollama`
locally, so a package missing from the image can survive every local test.

These tests make that failure loud and early instead.
"""

from __future__ import annotations

import importlib
import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# MODEL_PROVIDER value -> the module app/agent/model.py imports for it.
PROVIDER_MODULES = {
    "ollama": "langchain_ollama",
    "groq": "langchain_groq",
    "openai": "langchain_openai",
    "anthropic": "langchain_anthropic",
    "bedrock": "langchain_aws",
    "bedrock_openai": "aws_bedrock_token_generator",
}


@pytest.mark.parametrize(("provider", "module"), sorted(PROVIDER_MODULES.items()))
def test_every_provider_package_is_installed(provider: str, module: str):
    """Each MODEL_PROVIDER option must have its package installed.

    Failing here means a provider is selectable via config but would raise
    ModuleNotFoundError at runtime.
    """
    importlib.import_module(module)


def _pyproject_dependency_names() -> set[str]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    names = set()
    for spec in data["project"]["dependencies"]:
        names.add(re.split(r"[<>=!\[;\s]", spec, maxsplit=1)[0].strip().lower())
    return names


def _requirements_names() -> set[str]:
    names = set()
    for line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        names.add(re.split(r"[<>=!\[;\s]", line, maxsplit=1)[0].strip().lower())
    return names


def test_requirements_are_a_subset_of_pyproject():
    """The Dockerfile installs from pyproject.toml, not requirements.txt.

    Anything listed only in requirements.txt is therefore absent from the built
    image — it works locally and fails in the container.
    """
    missing = _requirements_names() - _pyproject_dependency_names()
    assert not missing, (
        f"in requirements.txt but not pyproject.toml, so missing from the Docker "
        f"image: {sorted(missing)}"
    )
