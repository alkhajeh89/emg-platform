import pytest
from emg_api_contracts import ApiResponse, PaginatedResponse, PaginationParams


def test_api_response_success():
    resp: ApiResponse[str] = ApiResponse(data="ok", error=None, correlation_id="cid-1")
    assert resp.data == "ok"
    assert resp.error is None


def test_pagination_params_validation():
    PaginationParams(page=1, page_size=10)
    with pytest.raises(ValueError):
        PaginationParams(page=0)
    with pytest.raises(ValueError):
        PaginationParams(page_size=0)


def test_paginated_response_total_pages():
    page = PaginatedResponse(items=[1, 2, 3], page=1, page_size=10, total_items=25)
    assert page.total_pages == 3
