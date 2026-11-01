from datetime import datetime, timezone

import pytest

from eccc_msc_amqp_alerts.wmo_header import decode_header


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "now, yyggggg, expected",
    [
        pytest.param(
            utc(2026, 10, 31, 15, 0), "311430", utc(2026, 10, 31, 14, 30), id="same day"
        ),
        pytest.param(
            utc(2026, 10, 15, 12, 0), "011200", utc(2026, 10, 1, 12, 0), id="earlier"
        ),
        # The month and year aren't in the header, so a bulletin from late last month
        # that arrives on the 1st must not be read as this month
        pytest.param(
            utc(2026, 11, 1, 0, 5),
            "312350",
            utc(2026, 10, 31, 23, 50),
            id="31st arriving on the 1st",
        ),
        pytest.param(
            utc(2026, 12, 1, 0, 5),
            "302355",
            utc(2026, 11, 30, 23, 55),
            id="30th arriving on the 1st",
        ),
        pytest.param(
            utc(2027, 1, 1, 0, 5),
            "312350",
            utc(2026, 12, 31, 23, 50),
            id="across new year",
        ),
        # Bulletins can be stamped a little ahead of our clock
        pytest.param(
            utc(2026, 10, 31, 23, 58),
            "010000",
            utc(2026, 11, 1, 0, 0),
            id="next month, just ahead",
        ),
    ],
)
def test_infers_month_and_year_closest_to_now(now, yyggggg, expected):
    header = decode_header(f"WWCN11 CWTO {yyggggg}", now=now)

    assert header["datetime"] == expected


def test_decodes_header_fields():
    header = decode_header("WWCN11 CWTO 311430", now=utc(2026, 10, 31, 15, 0))

    assert header["data_type"] == "data/core/weather/advisories-warnings"
    assert header["area"] == "Canada"
    assert header["centre"] == "Toronto Atmospheric Observatory"


def test_rejects_malformed_headers():
    with pytest.raises(ValueError):
        decode_header("not a header")
