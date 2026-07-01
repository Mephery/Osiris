"""Tests unitaires de validate_mac (main.py)."""
import pytest
from fastapi import HTTPException
from main import validate_mac


@pytest.mark.parametrize("raw,expected", [
    ("aa:bb:cc:dd:ee:ff", "aabbccddeeff"),
    ("AA:BB:CC:DD:EE:FF", "aabbccddeeff"),
    ("AA-BB-CC-DD-EE-FF", "aabbccddeeff"),
    ("aabbccddeeff",      "aabbccddeeff"),
    ("00:1A:2B:3C:4D:5E", "001a2b3c4d5e"),
])
def test_validate_mac_accepte_les_formats_valides(raw, expected):
    assert validate_mac(raw) == expected


@pytest.mark.parametrize("raw", [
    "pas-une-mac",
    "aa:bb:cc:dd:ee",           # trop court (10 hex)
    "aa:bb:cc:dd:ee:ff:00",     # trop long (14 hex)
    "zz:zz:zz:zz:zz:zz",        # caractères hors [0-9a-f]
    "",
    "aa bb cc dd ee ff",         # espaces : pas de strip
    ":::::::",
])
def test_validate_mac_rejette_les_formats_invalides(raw):
    with pytest.raises(HTTPException) as exc:
        validate_mac(raw)
    assert exc.value.status_code == 400


def test_validate_mac_normalise_en_minuscules():
    result = validate_mac("FF:FF:FF:FF:FF:FF")
    assert result == "ffffffffffff"
    assert result.islower()
