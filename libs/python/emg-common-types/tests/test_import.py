from emg_common_types import Classification, new_correlation_id


def test_classification_values():
    assert Classification.UNCLASSIFIED == "UNCLASSIFIED"
    assert {c.value for c in Classification} == {
        "UNCLASSIFIED",
        "INTERNAL",
        "CONFIDENTIAL",
        "SECRET",
    }


def test_new_correlation_id_is_unique():
    a, b = new_correlation_id(), new_correlation_id()
    assert a != b
    assert isinstance(a, str)
