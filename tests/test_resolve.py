from vsm.analysis.resolve import build_lexicon, resolve_signals
from vsm.topics.model import Topic

TOPIC = Topic(
    topic_id="t1", name="OIC pulse", therapeutic_area="gastroenterology",
    spend_band="standard", created_at="2026-08-25T00:00:00+00:00",
    brand="Symproic", molecule="naldemedine", competitors=("Relistor", "Movantik"),
)


def sig(sid, text):
    return {"signal_id": sid, "venue": "example.org", "theme": text,
            "excerpt": text, "url": f"https://example.org/{sid}"}


def test_brand_and_molecule_collapse_to_one_entity():
    ents = build_lexicon(TOPIC)
    ours = [e for e in ents if e.role == "ours"]
    assert len(ours) == 1
    assert set(ours[0].aliases) >= {"symproic", "naldemedine"}


def test_each_competitor_is_its_own_entity():
    ents = build_lexicon(TOPIC)
    assert {e.canonical for e in ents if e.role == "competitor"} == {"Relistor", "Movantik"}


def test_two_names_for_our_product_resolve_to_the_same_node():
    ents = build_lexicon(TOPIC)
    out = resolve_signals([sig("s1", "Symproic tolerability"), sig("s2", "naldemedine dosing")], ents)
    assert out["by_signal"]["s1"] == out["by_signal"]["s2"]
    # Pinned to the real entity id, not just to each other, so a broken
    # resolver that maps everything to [] cannot pass this by accident.
    assert out["by_signal"]["s1"] == ["ent-symproic"]


def test_matching_is_whole_word_not_substring():
    """'Movantik' must not match inside 'Movantikular'. Substring matching is
    how a brand monitor ends up reporting on an unrelated product."""
    ents = build_lexicon(TOPIC)
    out = resolve_signals([sig("s1", "the Movantikular approach")], ents)
    assert out["by_signal"]["s1"] == []


def test_matching_is_case_insensitive():
    ents = build_lexicon(TOPIC)
    out = resolve_signals([sig("s1", "RELISTOR was discussed")], ents)
    assert len(out["by_signal"]["s1"]) == 1


def test_a_signal_matching_nothing_is_recorded_not_dropped():
    ents = build_lexicon(TOPIC)
    out = resolve_signals([sig("s1", "unrelated chatter")], ents)
    assert out["by_signal"]["s1"] == []
    assert "s1" in out["unmapped_mentions"]
