from vsm.analysis.cluster import cluster_themes, kind_mix_for, venue_mix_for


def sig(sid, venue, theme):
    return {"signal_id": sid, "venue": venue, "theme": theme,
            "url": f"https://{venue}/{sid}", "title": theme}


ROWS = [
    sig("a", "studentdoctor.net", "tolerability"),
    sig("b", "studentdoctor.net", "tolerability"),
    sig("c", "patient.info", "cost"),
]


def test_offline_clustering_groups_on_the_derived_theme():
    themes = cluster_themes(ROWS, client=None)
    assert {t.name for t in themes} == {"tolerability", "cost"}


def test_volume_is_counted_not_asked_for():
    themes = {t.name: t for t in cluster_themes(ROWS, client=None)}
    assert themes["tolerability"].volume == 2
    assert themes["cost"].volume == 1


def test_venue_mix_counts_signals_per_venue():
    assert venue_mix_for(ROWS) == {"studentdoctor.net": 2, "patient.info": 1}


def test_kind_mix_uses_the_registry():
    mix = kind_mix_for(ROWS)
    assert mix.get("hcp_discussion") == 2
    assert mix.get("patient_community") == 1


def test_a_model_supplied_volume_is_ignored():
    """The model names themes. It does not count them: a number a model
    produced is a number nobody can reproduce."""

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"themes": [
                    {"theme_id": "th-1", "name": "tolerability",
                     "signal_ids": ["a", "b"], "volume": 9999}
                ]}
                reason = ""
            return _Out()

    themes = cluster_themes(ROWS[:2], client=_Client())
    assert themes[0].volume == 2


def test_duplicate_signal_ids_from_the_model_do_not_inflate_volume():
    """A repeated id in the model's list must count once, in first-seen
    order — otherwise the same signal is counted into volume twice, which
    is exactly the "a number nobody can reproduce" failure this pass exists
    to prevent, just introduced through a duplicate rather than an invented
    number."""

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"themes": [
                    {"theme_id": "th-1", "name": "tolerability",
                     "signal_ids": ["a", "a", "b"]}
                ]}
                reason = ""
            return _Out()

    themes = cluster_themes(ROWS[:2], client=_Client())
    assert themes[0].signal_ids == ("a", "b")
    assert themes[0].volume == 2


def test_an_unknown_signal_id_from_the_model_is_dropped():
    """The model may hallucinate an id. It cannot conjure a signal into the
    ledger by naming one."""

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"themes": [
                    {"theme_id": "th-1", "name": "tolerability",
                     "signal_ids": ["a", "does-not-exist"]}
                ]}
                reason = ""
            return _Out()

    themes = cluster_themes(ROWS[:1], client=_Client())
    assert themes[0].signal_ids == ("a",)
    assert themes[0].volume == 1
