from app.core.url import build_path, parse_path, parse_partial_path, slugify


def test_slugify():
    assert slugify("Assassination of Julius Caesar") == "assassination-of-julius-caesar"
    assert slugify("Apollo 11 Moon Landing!") == "apollo-11-moon-landing"


def test_build_path():
    path = build_path(
        1969,
        7,
        20,
        "2056",
        "United States",
        "Florida",
        "Cape Canaveral",
        "Apollo 11 Moon Landing",
    )
    assert (
        path
        == "/1969/july/20/2056/united-states/florida/cape-canaveral/apollo-11-moon-landing"
    )


def test_build_path_negative_year():
    path = build_path(
        -44, 3, 15, "1030", "Italy", "Lazio", "Rome", "Assassination of Julius Caesar"
    )
    assert path == "/-44/march/15/1030/italy/lazio/rome/assassination-of-julius-caesar"


def test_parse_path():
    result = parse_path(
        "/-44/march/15/1030/italy/lazio/rome/assassination-of-julius-caesar"
    )
    assert result is not None
    assert result["year"] == -44
    assert result["month"] == 3
    assert result["month_name"] == "march"
    assert result["day"] == 15
    assert result["slug"] == "assassination-of-julius-caesar"


def test_parse_path_round_trip():
    path = build_path(
        1945, 7, 16, "0530", "United States", "New Mexico", "Socorro", "Trinity Test"
    )
    parsed = parse_path(path)
    assert parsed is not None
    rebuilt = build_path(
        parsed["year"],
        parsed["month"],
        parsed["day"],
        parsed["time"],
        parsed["country"],
        parsed["region"],
        parsed["city"],
        parsed["slug"],
    )
    assert rebuilt == path


def test_parse_path_invalid():
    assert parse_path("/not/enough/segments") is None
    assert parse_path("/1969/badmonth/20/2056/us/fl/cc/slug") is None


def test_parse_partial_path_empty():
    assert parse_partial_path("") == {}


def test_parse_partial_path_year():
    result = parse_partial_path("1969")
    assert result["year"] == 1969


def test_parse_partial_path_year_month():
    result = parse_partial_path("1969/july")
    assert result["year"] == 1969
    assert result["month"] == "july"
    assert result["month_num"] == 7


def test_parse_partial_path_negative_year():
    result = parse_partial_path("-44/march/15")
    assert result["year"] == -44
    assert result["month"] == "march"
    assert result["day"] == 15
