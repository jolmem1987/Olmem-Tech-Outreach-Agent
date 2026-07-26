from outreach.catalog import LOCAL_CATALOG_PATH, load_local_catalog


def test_shipped_catalog_file_is_valid() -> None:
    """The committed catalog is what the Import button activates - keep it loadable."""
    catalog = load_local_catalog()
    assert catalog.generated_from == "manifest"
    assert catalog.catalog_version
    assert len(catalog.offers) >= 1
    for offer in catalog.offers:
        assert offer.allowed_claims, f"{offer.offer_key} has no allowed_claims"
        assert offer.evidence_urls, f"{offer.offer_key} has no evidence_urls"
        assert offer.landing_url.startswith("https://")


def test_catalog_version_tracks_content() -> None:
    """Editing offers must produce a new version so prospects are rescored."""
    first = load_local_catalog()
    second = load_local_catalog(LOCAL_CATALOG_PATH)
    assert first.catalog_version == second.catalog_version
