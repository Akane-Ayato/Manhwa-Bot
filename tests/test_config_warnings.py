from config import Vars, config_warnings


def test_warns_about_unknown_site_codes(monkeypatch):
    monkeypatch.setattr(Vars, "MAP_SITES", ("18fx", "nope"))
    assert any("nope" in w for w in config_warnings())


def test_default_sites_are_all_known():
    assert not any("unknown codes" in w for w in config_warnings())


def test_fonts_are_bundled():
    assert not any("fonts" in w for w in config_warnings())
