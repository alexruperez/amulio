from amulio.i18n import resolve_locale, translate


def test_configuration_locales_default_to_english_and_have_spanish_translations():
    assert resolve_locale(None) == "en"
    assert resolve_locale("unsupported") == "en"
    assert resolve_locale("es") == "es"
    assert translate("en", "install") == "Install in Stremio"
    assert translate("es", "install") == "Instalar en Stremio"
