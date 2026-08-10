import pytest
from emg_memory_graph import SEARCH_NORMALIZER_VERSION, normalize_search_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Alpha\t BETA  ", "alpha beta"),
        ("ＡＣＭＥ", "acme"),
        ("Straße", "strasse"),
        ("مُؤَسَّسَة", "مُؤَسَّسَة"),
    ],
)
def test_governed_normalization_vectors(raw, expected):
    assert normalize_search_text(raw) == expected


def test_normalizer_version_and_bounds():
    assert SEARCH_NORMALIZER_VERSION == 1
    with pytest.raises(ValueError):
        normalize_search_text("   ")
    with pytest.raises(ValueError):
        normalize_search_text("x" * 129)
    with pytest.raises(ValueError):
        normalize_search_text("bad\x00query")
