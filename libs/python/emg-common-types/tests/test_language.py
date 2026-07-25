import pytest
from emg_common_types import LanguageCode, Locale, TextDirection


def test_language_code_values():
    assert LanguageCode.ARABIC == "ar"
    assert LanguageCode.ENGLISH == "en"
    assert {code.value for code in LanguageCode} == {"ar", "en"}


def test_locale_direction_is_derived_from_language():
    assert Locale(language=LanguageCode.ARABIC).direction == TextDirection.RTL
    assert Locale(language=LanguageCode.ENGLISH).direction == TextDirection.LTR


def test_locale_tag_without_region():
    assert Locale(language=LanguageCode.ARABIC).tag == "ar"
    assert Locale(language=LanguageCode.ENGLISH).tag == "en"


def test_locale_tag_with_region():
    locale = Locale(language=LanguageCode.ARABIC, region="SA")
    assert locale.tag == "ar-SA"
    assert locale.direction == TextDirection.RTL


def test_locale_is_immutable_namedtuple():
    locale = Locale(language=LanguageCode.ENGLISH)
    with pytest.raises(AttributeError):
        locale.language = LanguageCode.ARABIC  # type: ignore[misc]


def test_locale_parse_language_only():
    assert Locale.parse("ar") == Locale(language=LanguageCode.ARABIC)
    assert Locale.parse("en") == Locale(language=LanguageCode.ENGLISH)


def test_locale_parse_is_case_insensitive_for_language():
    assert Locale.parse("AR") == Locale(language=LanguageCode.ARABIC)
    assert Locale.parse("En") == Locale(language=LanguageCode.ENGLISH)


def test_locale_parse_with_region_normalizes_to_uppercase():
    assert Locale.parse("ar-sa") == Locale(language=LanguageCode.ARABIC, region="SA")
    assert Locale.parse("en-US").region == "US"


def test_locale_parse_rejects_empty_tag():
    with pytest.raises(ValueError, match="must not be empty"):
        Locale.parse("")


def test_locale_parse_rejects_unsupported_language():
    with pytest.raises(ValueError, match="unsupported language"):
        Locale.parse("fr")


def test_locale_parse_rejects_malformed_region():
    with pytest.raises(ValueError, match="malformed region subtag"):
        Locale.parse("ar-SAU")
    with pytest.raises(ValueError, match="malformed region subtag"):
        Locale.parse("ar-1")


def test_locale_parse_rejects_too_many_subtags():
    with pytest.raises(ValueError, match="malformed locale tag"):
        Locale.parse("ar-SA-extra")


def test_locale_parse_rejects_header_injection_style_input():
    # BCP 47 allow-listing (ADR-021 Security Implications) must reject
    # anything outside language[-REGION] shape, not just obviously wrong tags.
    with pytest.raises(ValueError):
        Locale.parse("ar; rm -rf /")
    with pytest.raises(ValueError):
        Locale.parse("../../etc/passwd")
