import pytest
from pydantic import ValidationError
from api import LoginCredentials


def test_cloud_login_requires_the_configured_email():
    with pytest.raises(ValidationError):
        LoginCredentials(email="admin", password="test-only-password")
    assert LoginCredentials(email=" Owner@Example.Test ", password="test-only-password").email == "owner@example.test"
