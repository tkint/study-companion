import pytest

from app.auth.crypto import DecryptError, decrypt_secret, encrypt_secret, hash_password, verify_password
from app.cli import main

KEY = "k" * 64


def test_encrypt_round_trip_and_randomised():
    a = encrypt_secret(KEY, "0123456789abcdef0123456789abcdef")
    b = encrypt_secret(KEY, "0123456789abcdef0123456789abcdef")
    assert a != b and "0123456789abcdef" not in a
    assert decrypt_secret(KEY, a) == "0123456789abcdef0123456789abcdef"
    assert decrypt_secret(KEY, encrypt_secret(KEY, "é" * 100)) == "é" * 100


def test_decrypt_rejects_wrong_key_and_tampering():
    token = encrypt_secret(KEY, "secret")
    with pytest.raises(DecryptError):
        decrypt_secret("x" * 64, token)
    tampered = token[:-6] + ("A" if token[-6] != "A" else "B") + token[-5:]
    with pytest.raises(DecryptError):
        decrypt_secret(KEY, tampered)
    for bad in ["", "v2:abc", "v1:", "v1:!!!"]:
        with pytest.raises(DecryptError):
            decrypt_secret(KEY, bad)


def test_password_hash():
    stored = hash_password("correct horse battery staple")
    assert stored.startswith("scrypt$")
    assert verify_password(stored, "correct horse battery staple")
    assert not verify_password(stored, "wrong")
    assert not verify_password("garbage", "x")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "correct horse battery staple")
    monkeypatch.setenv("SECRET_KEY", KEY)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def test_cli_snapshot_db(env, capsys):
    assert main(["snapshot-db"]) == 0
    assert (env / "backup" / "app.db").exists()


def test_cli_check_without_moodle(env, capsys):
    assert main(["check"]) == 1
    assert "settings page" in capsys.readouterr().err


def test_cli_reset_password(env, monkeypatch, capsys):
    from app import accounts
    from app.config import Settings
    from app.db import make_engine

    answers = iter(["another long password", "another long password"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": next(answers))
    assert main(["reset-password"]) == 0
    engine = make_engine(Settings.from_env().data_dir)
    assert accounts.verify_password(engine, "another long password")
