from amulio.profiles import ProfilePreferences, ProfileStore


def test_profiles_are_persistent_and_have_english_defaults(tmp_path):
    store = ProfileStore(str(tmp_path / "amulio.sqlite3"))
    try:
        profile = store.create()
        loaded = store.get(profile.id)
    finally:
        store.close()

    assert len(profile.id) >= 24
    assert loaded == profile
    assert loaded.preferences.schema_version == 1
    assert loaded.preferences.ui_language == "en"
    assert loaded.preferences.search_languages == ("en", "es")


def test_profiles_can_be_updated_and_revoked(tmp_path):
    store = ProfileStore(str(tmp_path / "amulio.sqlite3"))
    try:
        profile = store.create()
        preferences = ProfilePreferences(
            ui_language="es",
            search_languages=("es", "en"),
            allow_season_packs=True,
            result_limit=25,
            max_size_gb=15,
        )
        updated = store.update(profile.id, preferences)
        revoked = store.revoke(profile.id)
    finally:
        store.close()

    assert updated is not None
    assert updated.preferences == preferences
    assert revoked is True

    reopened = ProfileStore(str(tmp_path / "amulio.sqlite3"))
    try:
        assert reopened.get(profile.id) is None
        assert reopened.revoke(profile.id) is False
    finally:
        reopened.close()


def test_rotating_a_profile_preserves_preferences_and_revokes_the_old_id(tmp_path):
    store = ProfileStore(str(tmp_path / "amulio.sqlite3"))
    try:
        original = store.create(ProfilePreferences(ui_language="es", result_limit=20))
        replacement = store.rotate(original.id)
        old_profile = store.get(original.id)
    finally:
        store.close()

    assert replacement is not None
    assert replacement.id != original.id
    assert replacement.preferences == original.preferences
    assert old_profile is None
