import pytest

from vsm.errors import NoSuchTopic
from vsm.topics.model import BANDS, band_for
from vsm.topics.store import TopicStore


@pytest.fixture
def store(tmp_path):
    return TopicStore(tmp_path / "t.db")


def test_the_three_bands_exist_and_escalate():
    """A preset rather than a dollar figure, because the four knobs interact
    and a dollar target gives no guidance on which one to move."""
    assert set(BANDS) == {"probe", "standard", "deep"}
    widths = [BANDS[n].queries_per_cluster for n in ("probe", "standard", "deep")]
    assert widths == sorted(widths) and len(set(widths)) == 3


def test_probe_buys_no_page_fetches():
    """An Unlocker fetch is 20x a SERP call. A probe is for finding out whether
    a topic has any conversation at all; it should not pay to read pages."""
    assert BANDS["probe"].page_fetches_per_cluster == 0


def test_band_for_rejects_an_unknown_name():
    with pytest.raises(KeyError):
        band_for("enormous")


def test_create_and_read_back(store):
    t = store.create(
        name="OIC pulse",
        brand="Symproic",
        molecule="naldemedine",
        therapeutic_area="gastroenterology",
        competitors=("Relistor", "Movantik"),
        questions=("what do prescribers say about tolerability?",),
        spend_band="standard",
        never_say=("Symproic",),
    )
    again = store.get(t.topic_id)
    assert again == t
    assert again.competitors == ("Relistor", "Movantik")


def test_get_unknown_raises(store):
    with pytest.raises(NoSuchTopic):
        store.get("nope")


def test_list_is_newest_first(store):
    a = store.create(name="A", therapeutic_area="gi", spend_band="probe")
    b = store.create(name="B", therapeutic_area="gi", spend_band="probe")
    assert [t.topic_id for t in store.list()][:2] == [b.topic_id, a.topic_id]


def test_update_returns_the_new_state(store):
    t = store.create(name="A", therapeutic_area="gi", spend_band="probe")
    t2 = store.update(t.topic_id, spend_band="deep")
    assert t2.spend_band == "deep"
    assert store.get(t.topic_id).spend_band == "deep"
