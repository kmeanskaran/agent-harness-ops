"""Request validation and project identity — the two pure pieces of the HTTP
layer that can be tested without Postgres, Redis or a model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.db import project_id_for_readme
from app.models import ContentRequest


class TestContentRequest:
    def test_minimal_request_gets_sensible_defaults(self):
        req = ContentRequest(email="dev@example.com", readme="# Hi")
        assert req.learnings == [] and req.hard_parts == [] and req.platforms == []
        assert req.tone and req.audience

    def test_readme_is_required_and_non_empty(self):
        with pytest.raises(ValidationError):
            ContentRequest(email="dev@example.com", readme="")

    def test_readme_over_100kb_is_rejected(self):
        # The cap exists so a huge README can't blow the context budget.
        with pytest.raises(ValidationError):
            ContentRequest(email="dev@example.com", readme="x" * 100_001)

    def test_email_is_required(self):
        with pytest.raises(ValidationError):
            ContentRequest(readme="# Hi")


class TestProjectId:
    def test_is_deterministic(self):
        readme = "# Project\n\nSome text."
        assert project_id_for_readme(readme) == project_id_for_readme(readme)

    def test_ignores_trailing_whitespace_so_edits_stay_one_project(self):
        assert project_id_for_readme("# A\nline") == project_id_for_readme("# A  \nline   \n\n")

    def test_different_content_gives_a_different_id(self):
        assert project_id_for_readme("# A") != project_id_for_readme("# B")

    def test_is_a_short_stable_hex_id(self):
        pid = project_id_for_readme("# A")
        assert len(pid) == 24 and all(c in "0123456789abcdef" for c in pid)
