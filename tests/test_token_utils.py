"""Context-budget guards. These decide whether a job is rejected or silently
truncated before it ever reaches the model, so the boundaries matter."""

from __future__ import annotations

from app.agent.token_utils import estimate_tokens, truncate_readme, validate_readme_size


class TestValidateReadmeSize:
    def test_accepts_a_normal_readme(self):
        ok, msg = validate_readme_size("# Project\n\nA short readme.")
        assert ok and msg == ""

    def test_rejects_on_character_limit(self):
        ok, msg = validate_readme_size("x" * 60_000, max_chars=50_000)
        assert not ok
        assert "60000 chars" in msg

    def test_rejects_on_token_limit_before_character_limit(self):
        # Under max_chars but over max_tokens — the token check must still fire.
        ok, msg = validate_readme_size("x" * 40_000, max_chars=50_000, max_tokens=1_000)
        assert not ok
        assert "tokens" in msg

    def test_boundary_is_inclusive(self):
        text = "x" * 100
        ok, _ = validate_readme_size(text, max_chars=100, max_tokens=estimate_tokens(text))
        assert ok


class TestTruncateReadme:
    def test_returns_input_unchanged_when_under_budget(self):
        readme = "# Small\n\nnothing to cut."
        assert truncate_readme(readme, max_tokens=10_000) == readme

    def test_shortens_and_marks_oversized_input(self):
        readme = "# Big\n\n" + ("paragraph text.\n\n" * 2_000)
        out = truncate_readme(readme, max_tokens=1_000)
        assert len(out) < len(readme)
        assert "README truncated" in out

    def test_keeps_the_beginning_of_the_document(self):
        readme = "# Title\n\nthe opening matters.\n\n" + ("filler.\n\n" * 2_000)
        out = truncate_readme(readme, max_tokens=500)
        assert out.startswith("# Title")
