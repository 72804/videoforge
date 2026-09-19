from __future__ import annotations

import json

from docprod.archive.licensing import normalize_license_decision
from docprod.archive.wikimedia import HttpResponse, WikimediaCommonsProvider


class FakeTransport:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str, headers: dict[str, str], *, timeout: int = 30) -> HttpResponse:
        self.urls.append(url)
        if "list=search" in url:
            assert "srnamespace=6" in url
            body = {
                "query": {
                    "search": [
                        {"title": "File:Maple_warehouse.jpg", "pageid": 11},
                    ]
                }
            }
        elif "prop=imageinfo" in url:
            assert "iiprop=" in url
            body = {
                "query": {
                    "pages": {
                        "11": {
                            "pageid": 11,
                            "title": "File:Maple_warehouse.jpg",
                            "imageinfo": [
                                {
                                    "url": "https://upload.wikimedia.org/maple.jpg",
                                    "descriptionurl": (
                                        "https://commons.wikimedia.org/wiki/"
                                        "File:Maple_warehouse.jpg"
                                    ),
                                    "width": 1600,
                                    "height": 900,
                                    "mime": "image/jpeg",
                                    "mediatype": "BITMAP",
                                    "size": 1000,
                                    "extmetadata": {
                                        "Artist": {"value": "Jane Doe"},
                                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                        "LicenseUrl": {
                                            "value": "https://creativecommons.org/licenses/by-sa/4.0/"
                                        },
                                        "UsageTerms": {
                                            "value": "Creative Commons Attribution-Share Alike 4.0"
                                        },
                                        "AttributionRequired": {"value": "true"},
                                        "NonFree": {"value": "false"},
                                        "ImageDescription": {
                                            "value": "<p>Quebec warehouse barrels</p>"
                                        },
                                    },
                                }
                            ],
                        }
                    }
                }
            }
        else:
            body = {}
        return HttpResponse(status=200, body=json.dumps(body).encode())


def test_commons_search_namespace_and_extmetadata() -> None:
    provider = WikimediaCommonsProvider(transport=FakeTransport())
    results = provider.search_files("maple syrup warehouse", limit=8)
    assert len(results) == 1
    item = results[0]
    assert item.width == 1600
    assert "Jane" in item.artist
    assert "Quebec warehouse" in item.description
    assert item.decision == "AUTO_REUSABLE"


def test_license_matrix() -> None:
    assert (
        normalize_license_decision(license_short_name="Public Domain")[0] == "AUTO_REUSABLE"
    )
    assert normalize_license_decision(license_short_name="CC0")[0] == "AUTO_REUSABLE"
    by = normalize_license_decision(license_short_name="CC BY 4.0", artist="A")
    assert by[0] == "AUTO_REUSABLE"
    assert normalize_license_decision(license_short_name="")[0] == "REVIEW_REQUIRED"
    assert (
        normalize_license_decision(license_short_name="CC BY 4.0 or GFDL", artist="A")[0]
        == "REVIEW_REQUIRED"
    )
    assert normalize_license_decision(license_short_name="Fair use", non_free=True)[0] == "REJECT"
    assert (
        normalize_license_decision(
            license_short_name="CC BY 4.0", artist="A", restrictions="personality rights"
        )[0]
        == "REVIEW_REQUIRED"
    )


def test_archive_download_records_sha256(tmp_path) -> None:
    from hashlib import sha256

    from docprod.archive.downloader import download_archive_file

    class Transport:
        def get(self, url: str, headers: dict[str, str], *, timeout: int = 30) -> HttpResponse:
            return HttpResponse(status=200, body=b"commons-bytes")

    dest = tmp_path / "source.jpg"
    digest = download_archive_file(
        WikimediaCommonsProvider(transport=Transport()),
        "https://upload.example/file.jpg",
        dest,
    )
    assert dest.read_bytes() == b"commons-bytes"
    assert digest == sha256(b"commons-bytes").hexdigest()
