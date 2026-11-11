from datetime import datetime

from photosorter.routing.dates import (
    folder_for,
    parse_exif_date,
    parse_filename_date,
    resolve_date,
)

NOW = datetime(2026, 11, 9)


def test_exif_date_parsed():
    assert parse_exif_date("2024:06:15 12:34:56", NOW) == datetime(2024, 6, 15, 12, 34, 56)


def test_exif_zero_date_rejected():
    assert parse_exif_date("0000:00:00 00:00:00", NOW) is None
    assert parse_exif_date("", NOW) is None
    assert parse_exif_date(None, NOW) is None


def test_filename_patterns():
    assert parse_filename_date("IMG_20240615_123456.jpg", NOW) == datetime(2024, 6, 15, 12, 34, 56)
    assert parse_filename_date("PXL_20240615_123456789.jpg", NOW) == datetime(2024, 6, 15, 12, 34, 56)
    assert parse_filename_date("IMG-20240615-WA0001.jpg", NOW) == datetime(2024, 6, 15)
    assert parse_filename_date("2024-06-15 12.34.56.heic", NOW) == datetime(2024, 6, 15, 12, 34, 56)


def test_filename_rejects_non_dates():
    assert parse_filename_date("IMG_0412.jpg", NOW) is None
    assert parse_filename_date("IMG_99991399.jpg", NOW) is None
    assert parse_filename_date("12345678.jpg", NOW) is None


def test_resolution_order():
    mtime = datetime(2020, 1, 2, 3, 4, 5).timestamp()
    assert resolve_date("2024:06:15 12:00:00", "IMG_20230101_000000.jpg", mtime, NOW)[1] == "exif"
    assert resolve_date(None, "IMG_20230101_000000.jpg", mtime, NOW)[1] == "filename"
    dt, source = resolve_date(None, "IMG_0412.jpg", mtime, NOW)
    assert source == "mtime" and dt.year == 2020
    assert resolve_date(None, "IMG_0412.jpg", None, NOW) == (None, "none")


def test_folder_for():
    assert folder_for(datetime(2024, 6, 15)) == "2024/06"
    assert folder_for(None) == "Undated"
