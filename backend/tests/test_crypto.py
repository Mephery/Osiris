"""Tests unitaires du chiffrement Fernet (crypto.py)."""
from crypto import encrypt, decrypt


def test_roundtrip():
    """Un texte chiffré puis déchiffré doit redonner l'original."""
    assert decrypt(encrypt("P@ssw0rd!2026")) == "P@ssw0rd!2026"


def test_roundtrip_special_chars():
    assert decrypt(encrypt("Ünïcödé & $ymb0ls!")) == "Ünïcödé & $ymb0ls!"


def test_ciphertext_differs_from_plaintext():
    secret = "monmotdepasse"
    assert encrypt(secret) != secret


def test_two_encryptions_differ():
    """Fernet utilise un IV aléatoire : deux chiffrés du même texte sont distincts."""
    assert encrypt("same") != encrypt("same")


def test_encrypt_empty_returns_empty():
    assert encrypt("") == ""


def test_decrypt_empty_returns_empty():
    assert decrypt("") == ""


def test_decrypt_invalid_token_returns_empty():
    assert decrypt("pas-un-token-fernet-valide") == ""


def test_decrypt_truncated_token_returns_empty():
    token = encrypt("secret")
    assert decrypt(token[:10]) == ""
