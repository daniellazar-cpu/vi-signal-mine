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
    number.

    The order is deliberately not alphabetical ("b" before "a"): a dedupe
    that quietly did ``sorted(set(ids))`` would produce the same result as
    correct first-seen-order dedupe on an already-sorted input like
    ["a", "a", "b"], so it would pass a weaker version of this test without
    actually preserving order. This input pins order, not just uniqueness."""

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"themes": [
                    {"theme_id": "th-1", "name": "tolerability",
                     "signal_ids": ["b", "a", "b", "a"]}
                ]}
                reason = ""
            return _Out()

    themes = cluster_themes(ROWS[:2], client=_Client())
    assert themes[0].signal_ids == ("b", "a")
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


def test_the_models_grouping_is_used_when_it_diverges_from_theme():
    """Every other client-path test in this file is built so the model's
    grouping happens to agree with the miner-derived `theme` field — which
    means those tests would still pass even if `cluster_themes` ignored
    `client` entirely and always ran `_offline`. This is the one fixture
    where the two disagree: "b" and "c" have different `theme` values
    ("tolerability" vs "cost"), so no offline grouping on ROWS could ever
    produce a single theme containing both. If this passes, the model's
    grouping was actually consulted."""

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"themes": [
                    {"theme_id": "th-1", "name": "off-label use",
                     "signal_ids": ["b", "c"]}
                ]}
                reason = ""
            return _Out()

    themes = cluster_themes(ROWS, client=_Client())
    assert len(themes) == 1
    assert themes[0].name == "off-label use"
    assert themes[0].signal_ids == ("b", "c")
    assert themes[0].volume == 2
    # The offline fallback on these same rows partitions strictly by `theme`
    # and could never merge a "tolerability" row with a "cost" row into one
    # group — so this name could only have come from the model's grouping.
    offline_names = {t.name for t in cluster_themes(ROWS, client=None)}
    assert "off-label use" not in offline_names


def test_model_returning_no_themes_falls_back_to_offline():
    """`out.data.get("themes", [])` can be an empty list without `out.ok`
    being false — a well-formed response that simply proposed nothing. That
    must not be reported as an empty analysis; it must read exactly like the
    offline pass, because an empty list here would render as "nothing was
    being discussed", which is not the same claim as "the model returned no
    groupings"."""

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"themes": []}
                reason = ""
            return _Out()

    themes = cluster_themes(ROWS, client=_Client())
    assert themes == cluster_themes(ROWS, client=None)


def test_model_themes_that_all_resolve_to_zero_rows_fall_back_to_offline():
    """Every proposed theme's signal_ids are ids absent from the ledger, so
    every proposed theme is skipped for resolving to zero rows — the loop
    produces an empty `themes` list by a different route than the previous
    test (post-filtering, not an empty proposal), and must land on the same
    fallback rather than reporting nothing."""

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"themes": [
                    {"theme_id": "th-1", "name": "ghost",
                     "signal_ids": ["does-not-exist-1", "does-not-exist-2"]},
                ]}
                reason = ""
            return _Out()

    themes = cluster_themes(ROWS, client=_Client())
    assert themes == cluster_themes(ROWS, client=None)
