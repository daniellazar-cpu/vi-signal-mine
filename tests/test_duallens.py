import pytest

from vsm.analysis.cluster import Theme
from vsm.analysis.duallens import dual_lens, net_stance
from vsm.analysis.stance import ThemeStance


def theme(tid, name):
    return Theme(tid, name, ("a",), 1, {}, {})


def test_net_stance_runs_from_minus_one_to_one():
    assert net_stance({"positive": 4}) == pytest.approx(1.0)
    assert net_stance({"negative": 4}) == pytest.approx(-1.0)
    assert net_stance({"positive": 2, "negative": 2}) == pytest.approx(0.0)


def test_unclear_and_mixed_do_not_move_the_net_but_do_dilute_it():
    """An abstention is not agreement. It stays in the denominator so a theme
    the model could not read does not look like a confident zero."""
    assert net_stance({"positive": 1, "unclear": 3}) == pytest.approx(0.25)


def test_a_class_with_no_readable_stance_is_none_not_zero():
    assert net_stance({}) is None
    assert net_stance({"unclear": 5}) == pytest.approx(0.0)


def test_divergence_is_the_gap_between_the_two_lenses():
    stances = [ThemeStance("t1", {"hcp": {"positive": 4}, "patient": {"negative": 4}}, "venue")]
    gap = dual_lens([theme("t1", "tolerability")], stances)[0]
    assert gap.hcp_net == pytest.approx(1.0)
    assert gap.patient_net == pytest.approx(-1.0)
    assert gap.divergence == pytest.approx(2.0)


def test_themes_are_ranked_by_divergence():
    themes = [theme("t1", "small"), theme("t2", "large")]
    stances = [
        ThemeStance("t1", {"hcp": {"positive": 1}, "patient": {"positive": 1}}, "venue"),
        ThemeStance("t2", {"hcp": {"positive": 4}, "patient": {"negative": 4}}, "venue"),
    ]
    assert [g.theme_id for g in dual_lens(themes, stances)] == ["t2", "t1"]


def test_a_one_sided_theme_has_no_divergence_and_says_why():
    """Silence from one side is not agreement, and it is not a gap of zero."""
    stances = [ThemeStance("t1", {"hcp": {"positive": 3}}, "venue")]
    gap = dual_lens([theme("t1", "clinical only")], stances)[0]
    assert gap.divergence is None
    # Names the side that spoke, in plain words — "hcp"/"signal" are banned from
    # anything a reader (or the client report) sees. Clinicians spoke here.
    assert "only clinicians" in gap.reason.lower()
    assert "silence is not agreement" in gap.reason.lower()


def test_a_patient_only_theme_has_no_divergence_and_names_the_silent_side():
    """The mirror image of the clinical-only case: clinicians are silent."""
    stances = [ThemeStance("t1", {"patient": {"negative": 3}}, "venue")]
    gap = dual_lens([theme("t1", "patient only")], stances)[0]
    assert gap.divergence is None
    assert "only patients" in gap.reason.lower()


def test_a_theme_with_neither_class_present_does_not_blame_one_side():
    """Themes built purely from institutional venues (journals, guideline
    bodies, labels — all mapped to ``institutional`` in KIND_TO_CLASS) have
    no hcp signal and no patient signal at all. The reason must not claim
    only one side is silent when neither spoke — that would tell a reader
    the wrong side had something to say."""
    stances = [ThemeStance("t1", {"institutional": {"neutral": 2}}, "venue")]
    gap = dual_lens([theme("t1", "institutional only")], stances)[0]
    assert gap.hcp_net is None
    assert gap.patient_net is None
    assert gap.divergence is None
    # Neither side spoke — the reason must not blame one, and must name both.
    assert "neither clinicians nor patients" in gap.reason.lower()


def test_unmeasurable_themes_sort_last():
    themes = [theme("t1", "one sided"), theme("t2", "both sides")]
    stances = [
        ThemeStance("t1", {"hcp": {"positive": 3}}, "venue"),
        ThemeStance("t2", {"hcp": {"positive": 1}, "patient": {"negative": 1}}, "venue"),
    ]
    assert [g.theme_id for g in dual_lens(themes, stances)] == ["t2", "t1"]
