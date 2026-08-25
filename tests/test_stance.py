import dataclasses

from vsm.analysis.authorclass import AuthorClass, VenueResolver
from vsm.analysis.cluster import cluster_themes
from vsm.analysis.stance import STANCES, ThemeStance, stance_for_themes


def sig(sid, venue, theme):
    return {"signal_id": sid, "venue": venue, "theme": theme,
            "excerpt": theme, "title": theme, "url": f"https://{venue}/{sid}"}


ROWS = [
    sig("a", "studentdoctor.net", "tolerability"),
    sig("b", "patient.info", "tolerability"),
]


class _Client:
    def __init__(self, mapping):
        self.mapping = mapping

    def complete_structured(self, **kw):
        class _Out:
            ok = True
            data = {"items": [{"signal_id": k, "stance": v, "rationale": "t"}
                              for k, v in self.mapping.items()]}
            reason = ""
        return _Out()


def test_there_is_no_blended_stance_field():
    """Not a policy — there is nowhere to put one."""
    names = {f.name for f in dataclasses.fields(ThemeStance)}
    assert not {"overall", "blended", "sentiment", "score"} & names


def test_stance_is_reported_per_author_class():
    themes = cluster_themes(ROWS, client=None)
    out = stance_for_themes(themes, ROWS, VenueResolver(),
                            client=_Client({"a": "positive", "b": "negative"}))
    by_class = out[0].by_class
    assert by_class["hcp"]["positive"] == 1
    assert by_class["patient"]["negative"] == 1


def test_the_basis_is_recorded_on_the_result():
    """A report must be able to say whether 'hcp' meant a venue or an NPI."""
    themes = cluster_themes(ROWS, client=None)
    out = stance_for_themes(themes, ROWS, VenueResolver(), client=_Client({"a": "positive"}))
    assert out[0].basis == "venue"


def test_an_identity_resolver_changes_the_basis_and_nothing_else():
    """Spec §3.3 — swapping the resolver must not change the shape."""

    class StubIdentity:
        def resolve(self, signal):
            return AuthorClass("hcp", "identity", 0.97, "NPI matched", npi="1234567890")

    themes = cluster_themes(ROWS, client=None)
    venue = stance_for_themes(themes, ROWS, VenueResolver(), client=_Client({"a": "positive", "b": "positive"}))
    ident = stance_for_themes(themes, ROWS, StubIdentity(), client=_Client({"a": "positive", "b": "positive"}))
    assert set(venue[0].by_class) == {"hcp", "patient"}
    assert set(ident[0].by_class) == {"hcp"}
    assert venue[0].basis == "venue" and ident[0].basis == "identity"
    assert type(venue[0]) is type(ident[0])


def test_an_unrecognised_stance_from_the_model_becomes_unclear():
    themes = cluster_themes(ROWS, client=None)
    out = stance_for_themes(themes, ROWS, VenueResolver(),
                            client=_Client({"a": "ecstatic", "b": "neutral"}))
    assert out[0].by_class["hcp"]["unclear"] == 1


def test_without_a_client_every_signal_is_unclear_not_neutral():
    """No classifier ran. 'neutral' would be a finding; 'unclear' is the truth."""
    themes = cluster_themes(ROWS, client=None)
    out = stance_for_themes(themes, ROWS, VenueResolver(), client=None)
    assert out[0].by_class["hcp"] == {"unclear": 1}


def test_the_five_stances_are_fixed():
    assert STANCES == ("positive", "negative", "mixed", "neutral", "unclear")
