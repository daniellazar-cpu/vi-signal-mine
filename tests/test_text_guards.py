import pytest

from vsm.errors import GuardViolation
from vsm.guards.advisory import assert_advisory
from vsm.guards.claims import assert_no_unmeasured_claims
from vsm.guards.terms import assert_no_banned_terms


# ---------------------------------------------------------------- G2 advisory
@pytest.mark.parametrize("text", [
    "You should increase spend on the guideline venues.",
    "You must respond to the tolerability thread.",
    "We recommend that you brief the field team.",
    "The right move is to publish a correction.",
])
def test_g2_rejects_directives(text):
    with pytest.raises(GuardViolation, match="G2"):
        assert_advisory(text)


@pytest.mark.parametrize("text", [
    "Increasing spend on the guideline venues is worth considering.",
    "One option is to brief the field team.",
    "Teams in this position often respond in the thread; the trade-off is visibility.",
])
def test_g2_accepts_suggestions(text):
    assert assert_advisory(text) is None


def test_g2_is_case_insensitive():
    with pytest.raises(GuardViolation):
        assert_advisory("YOU MUST act on this.")


def test_g2_names_where_it_fired():
    with pytest.raises(GuardViolation, match="worth_considering.md"):
        assert_advisory("You should act.", where="worth_considering.md")


# ------------------------------------------------------------------- G4 terms
def test_g4_is_a_noop_with_no_terms():
    assert assert_no_banned_terms("Symproic is discussed widely", ()) is None


def test_g4_rejects_a_listed_term():
    with pytest.raises(GuardViolation, match="G4"):
        assert_no_banned_terms("Symproic is discussed widely", ("Symproic",))


def test_g4_matches_whole_words_only():
    """A never-say list that fires on substrings makes ordinary prose
    unwritable and gets switched off, which is worse than not having one."""
    assert assert_no_banned_terms("the Symproical approach", ("Symproic",)) is None


def test_g4_is_case_insensitive():
    with pytest.raises(GuardViolation):
        assert_no_banned_terms("SYMPROIC appears here", ("Symproic",))


# ------------------------------------------------------------------ G5 claims
@pytest.mark.parametrize("text", [
    "Discussion will grow through Q4.",
    "Volume is expected to reach 400 mentions.",
    "Projected uptake is 12%.",
    "Our model is 89% accurate.",
    "This predicts a rise in clinician interest.",
    "Mentions are forecast to double.",
])
def test_g5_rejects_forecasts_and_accuracy_claims(text):
    with pytest.raises(GuardViolation, match="G5"):
        assert_no_unmeasured_claims(text)


@pytest.mark.parametrize("text", [
    "Discussion grew 50% between the two snapshots.",
    "Volume reached 400 mentions in this snapshot.",
    "Tolerability was the most-discussed theme, on 3 independent sources.",
])
def test_g5_accepts_measured_statements(text):
    assert assert_no_unmeasured_claims(text) is None


def test_g5_does_not_fire_on_the_word_will_in_a_name():
    """A guard with false positives gets disabled. 'Willis' is not a forecast."""
    assert assert_no_unmeasured_claims("Dr Willis raised the dosing question.") is None
