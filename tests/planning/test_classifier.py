from __future__ import annotations

from docprod.planning.classifier import classify_text
from docprod.planning.models import ContentCategory


def test_english_document_and_location() -> None:
    document = classify_text("The report sat beside a newspaper clipping.", "en")
    assert document.primary_category in {ContentCategory.document, ContentCategory.news}
    assert "report" in document.matched_terms or "newspaper" in document.matched_terms

    location = classify_text("The train station in the city was empty.", "en")
    assert location.primary_category is ContentCategory.location_establishing
    assert "station" in location.matched_terms or "train station" in location.matched_terms


def test_english_money_police_phone() -> None:
    money = classify_text("A stack of money was in the wallet.", "en")
    assert money.primary_category is ContentCategory.money
    police = classify_text("The police officer arrived.", "en")
    assert police.primary_category is ContentCategory.police
    phone = classify_text("He called from a phone near the computer.", "en")
    assert phone.primary_category is ContentCategory.phone_or_computer


def test_turkish_keywords() -> None:
    bank = classify_text("Adam bankadan para aldı.", "tr")
    assert bank.primary_category in {ContentCategory.money, ContentCategory.action}
    assert any(term in bank.matched_terms for term in ("para", "banka"))

    police = classify_text("Polis memurları perona girdi.", "tr")
    assert police.primary_category is ContentCategory.police
    assert "polis" in police.matched_terms

    court = classify_text("Mahkeme tutanağı henüz yoktu.", "tr")
    assert court.primary_category is ContentCategory.court_or_legal

    phone = classify_text("Telefonunu açtı ve aradı.", "tr")
    assert phone.primary_category is ContentCategory.phone_or_computer or phone.motion_score >= 1


def test_turkish_cased_istasyon() -> None:
    result = classify_text("İstanbul'daki tren istasyonu boştu.", "tr")
    assert result.primary_category is ContentCategory.location_establishing
    assert any("istasyon" in term or "tren" in term for term in result.matched_terms)
