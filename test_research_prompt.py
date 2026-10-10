"""Discovery prompt must cover vendor challenges (Flova-class misses)."""
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "research_grants_mod", "research-grants.py")
r = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r)


def test_prompt_covers_challenges():
    t = r.PROMPT_TEMPLATE
    assert "creator competitions / challenges" in t
    assert "flova.ai/en/activity" in t
    assert "$1,000" in t
    assert "exposure-only" in t
    assert "HACKATHONS" in t
    assert "devpost.com/hackathons" in t


def test_prompt_allows_competition_values():
    t = r.PROMPT_TEMPLATE
    assert '"Competition"' in t
    assert '"prize"' in t
