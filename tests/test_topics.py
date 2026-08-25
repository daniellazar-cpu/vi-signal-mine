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


def test_persist_across_store_instances(tmp_path):
    """Proves that writes are committed and survive a fresh store instance."""
    db_path = tmp_path / "persist.db"
    store1 = TopicStore(db_path)
    t = store1.create(name="persistent", therapeutic_area="test", spend_band="probe")

    # Second store on the same path must see the topic.
    store2 = TopicStore(db_path)
    found = store2.get(t.topic_id)
    assert found == t


def test_create_rejects_unknown_spend_band(store):
    """Create must reject invalid spend bands."""
    with pytest.raises(KeyError, match="unknown spend band"):
        store.create(name="bad", therapeutic_area="test", spend_band="enormous")


def test_update_rejects_unknown_spend_band(store):
    """Update must reject invalid spend bands."""
    t = store.create(name="A", therapeutic_area="gi", spend_band="probe")
    with pytest.raises(KeyError, match="unknown spend band"):
        store.update(t.topic_id, spend_band="massive")


def test_update_rejects_created_at_column(store):
    """Update must reject attempts to modify the created_at timestamp."""
    t = store.create(name="A", therapeutic_area="gi", spend_band="probe")
    with pytest.raises(KeyError, match="column.*not updatable"):
        store.update(t.topic_id, created_at="2000-01-01T00:00:00Z")


def test_update_rejects_seq_column(store):
    """Update must reject attempts to modify the seq column."""
    t = store.create(name="A", therapeutic_area="gi", spend_band="probe")
    with pytest.raises(KeyError, match="column.*not updatable"):
        store.update(t.topic_id, seq=999)
