"""Parsing the finished agent workspace back into the API response.

This is the seam where free-form model output becomes a typed contract, so it's
where a regression is both most likely and least visible — a broken parse used
to return 200 with empty fields rather than raising. A total blank now raises
(see EmptyGenerationError); partial output still passes through quietly.
"""

from __future__ import annotations

import pytest

from app.agent.orchestrator import EmptyGenerationError, _parse_thread, assemble_result


def _files(**paths: str) -> dict:
    """Build a StateBackend-shaped files dict for job `j1`."""
    return {f"/workspace/j1/{name}.md": {"content": body} for name, body in paths.items()}


class TestParseThread:
    def test_splits_numbered_tweets(self):
        md = "1/ first tweet\n2/ second tweet\n3/ third tweet"
        assert _parse_thread(md) == ["first tweet", "second tweet", "third tweet"]

    def test_keeps_continuation_lines_with_their_tweet(self):
        md = "1/ opening line\nstill tweet one\n2/ tweet two"
        assert _parse_thread(md) == ["opening line\nstill tweet one", "tweet two"]

    def test_skips_markdown_headings(self):
        md = "# X Thread\n\n1/ only real tweet"
        assert _parse_thread(md) == ["only real tweet"]

    def test_tolerates_spacing_around_the_number(self):
        md = "  1 / spaced\n2/tight"
        assert _parse_thread(md) == ["spaced", "tight"]

    def test_unnumbered_or_empty_input_yields_nothing(self):
        assert _parse_thread("") == []
        assert _parse_thread("# Heading\n\njust prose, no numbering") == []


class TestAssembleResult:
    def test_returns_only_requested_platforms(self):
        files = _files(
            x_draft="1/ tweet",
            linkedin_draft="post body",
            devto_draft="# Article",
        )
        result = assemble_result(files, "j1", ["x"])
        assert result["x_thread"] == ["tweet"]
        assert "linkedin_post" not in result
        assert "devto_article" not in result

    def test_strips_leading_heading_from_linkedin_post(self):
        files = _files(linkedin_draft="# LinkedIn Post\n\nthe actual body")
        assert assemble_result(files, "j1", ["linkedin"])["linkedin_post"] == "the actual body"

    def test_missing_every_draft_file_raises(self):
        # Previously this returned empty strings, so a run where the agent wrote
        # nothing was stored as a successful blank post. That is how a MODEL_NAME
        # without tool-calling support failed silently in dev; it must be loud.
        with pytest.raises(EmptyGenerationError) as exc:
            assemble_result({}, "j1", ["x", "linkedin", "devto"])
        assert "MODEL_NAME" in str(exc.value)

    def test_partial_output_is_not_treated_as_failure(self):
        # One platform of three is a content problem for the reviewer, not the
        # structural failure the guard exists to catch.
        files = _files(linkedin_draft="post body")
        result = assemble_result(files, "j1", ["x", "linkedin"])
        assert result["linkedin_post"] == "post body"
        assert result["x_thread"] == []

    def test_review_notes_are_always_included(self):
        files = _files(review_notes="looks good")
        assert assemble_result(files, "j1", [])["review_notes"] == "looks good"
