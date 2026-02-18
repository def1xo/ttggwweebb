from app.services.importer_notifications import _extract_sizes


def test_extract_sizes_parses_multiple_size_lines_and_deduplicates():
    text = """
    Новинка
    Размер: S, M
    Размеры: M/L
    """
    assert _extract_sizes(text) == ["S", "M", "L"]


def test_extract_sizes_stops_before_other_fields_on_same_line():
    text = "Размеры: 42, 43 цвет: black"
    assert _extract_sizes(text) == ["42", "43"]
