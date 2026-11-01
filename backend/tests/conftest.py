import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

PASSWORD = "correct horse battery staple"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        app_password=PASSWORD,
        secret_key="s" * 64,
        data_dir=tmp_path,
        cookie_secure=False,  # TestClient talks plain HTTP
        login_max_attempts=3,
    )


@pytest.fixture
def client(settings) -> TestClient:
    return TestClient(create_app(settings), follow_redirects=False)
