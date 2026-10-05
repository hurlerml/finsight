from app.api.transactions import _page_window


def test_page_window_returns_next_offset_when_more_rows_exist() -> None:
    items, has_more, next_offset = _page_window([1, 2, 3, 4], offset=20, limit=3)

    assert items == [1, 2, 3]
    assert has_more is True
    assert next_offset == 23


def test_page_window_marks_last_page() -> None:
    items, has_more, next_offset = _page_window([1, 2], offset=40, limit=3)

    assert items == [1, 2]
    assert has_more is False
    assert next_offset is None
