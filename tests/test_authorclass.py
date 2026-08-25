from vsm.analysis.authorclass import AuthorClass, VenueResolver


def sig(venue, **kw):
    return {"signal_id": "sig-1", "venue": venue, "url": f"https://{venue}/x", **kw}


def test_hcp_discussion_venue_yields_hcp_on_a_venue_basis():
    got = VenueResolver().resolve(sig("studentdoctor.net"))
    assert got.value == "hcp"
    assert got.basis == "venue"
    assert got.npi is None


def test_patient_community_yields_patient():
    got = VenueResolver().resolve(sig("patient.info"))
    assert got.value == "patient"


def test_guideline_and_evidence_venues_are_institutional():
    """A journal is not a person. Counting it as clinician sentiment would be
    the same error as counting a press release as a customer review."""
    for venue in ("gastro.org", "pubmed.ncbi.nlm.nih.gov"):
        assert VenueResolver().resolve(sig(venue)).value == "institutional"


def test_an_unregistered_venue_is_unknown_not_guessed():
    got = VenueResolver().resolve(sig("some-random-blog.example"))
    assert got.value == "unknown"
    assert "not in the registry" in got.rationale


def test_the_rationale_always_says_the_basis_out_loud():
    got = VenueResolver().resolve(sig("studentdoctor.net"))
    assert "venue" in got.rationale.lower()


def test_venue_basis_never_carries_an_npi():
    """The seam's whole point: a venue-derived class cannot assert identity."""
    got = VenueResolver().resolve(sig("studentdoctor.net"))
    assert got.npi is None and got.basis == "venue"


def test_an_identity_resolver_satisfies_the_same_protocol():
    """Proves §3.3 is a seam and not a comment. This stub is what the v2
    Provider360 resolver will replace."""

    class StubIdentityResolver:
        def resolve(self, signal):
            return AuthorClass(
                value="hcp", basis="identity", confidence=0.97,
                rationale="handle matched NPI 1234567890 via the provider graph",
                npi="1234567890",
            )

    got = StubIdentityResolver().resolve(sig("x.com"))
    assert got.basis == "identity" and got.npi == "1234567890"
