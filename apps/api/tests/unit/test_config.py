"""Unit tests for the sandbox-only enforcement rule (docs/SECURITY.md §10)."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

import pytest

from app.core.config import PayPalEnv, Settings, _environment_file


@pytest.mark.parametrize(("config_path", "env_path"), [
    (PureWindowsPath("E:/repo/apps/api/app/core/config.py"), PureWindowsPath("E:/repo/.env")),
    (PurePosixPath("/workspace/paypal/apps/api/app/core/config.py"), PurePosixPath("/workspace/paypal/.env")),
    (PurePosixPath("/app/app/core/config.py"), PurePosixPath("/app/.env")),
])
def test_environment_file_handles_monorepo_and_container_layouts(config_path, env_path):
    assert _environment_file(config_path) == env_path


def test_sandbox_is_default():
    settings = Settings(_env_file=None)
    assert settings.paypal_env is PayPalEnv.SANDBOX


def test_live_without_explicit_allow_flag_is_rejected():
    with pytest.raises(ValueError, match="ALLOW_LIVE_PAYPAL"):
        Settings(_env_file=None, paypal_env=PayPalEnv.LIVE, allow_live_paypal=False)


def test_live_with_explicit_allow_flag_is_accepted():
    settings = Settings(_env_file=None, paypal_env=PayPalEnv.LIVE, allow_live_paypal=True)
    assert settings.paypal_env is PayPalEnv.LIVE


def test_empty_or_short_secret_key_is_rejected():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(_env_file=None, secret_key="")
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(_env_file=None, secret_key="short")


def test_production_requires_cors_origins():
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(_env_file=None, app_env="production", cors_origins="")
    settings = Settings(
        _env_file=None,
        app_env="production",
        cors_origins="https://app.example.com, https://admin.example.com/",
    )
    assert settings.cors_allow_origins == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_managed_database_urls_select_the_correct_drivers(scheme):
    raw = f"{scheme}://user:encoded%40password@private-db:5432/autopilot?connect_timeout=10"
    settings = Settings(_env_file=None, database_url=raw, database_url_sync=raw)
    suffix = raw.split("://", 1)[1]
    assert settings.database_url == f"postgresql+asyncpg://{suffix}"
    assert settings.database_url_sync == f"postgresql+psycopg://{suffix}"


def test_explicit_database_drivers_are_preserved():
    async_url = "postgresql+asyncpg://user:password@local/autopilot"
    sync_url = "postgresql+psycopg://user:password@local/autopilot"
    settings = Settings(_env_file=None, database_url=async_url, database_url_sync=sync_url)
    assert settings.database_url == async_url
    assert settings.database_url_sync == sync_url


@pytest.mark.parametrize("base_url", [
    "https://evilpaypal.com", "https://api-m.paypal.com", "http://api-m.sandbox.paypal.com",
    "https://user@api-m.sandbox.paypal.com", "https://api-m.sandbox.paypal.com/redirect",
])
def test_sandbox_rejects_untrusted_or_live_api_overrides(base_url):
    with pytest.raises(ValueError, match="PAYPAL_API_BASE_URL"):
        Settings(_env_file=None, paypal_api_base_url=base_url)


def test_sandbox_accepts_only_its_official_api_origin():
    settings = Settings(_env_file=None, paypal_api_base_url="https://api-m.sandbox.paypal.com/")
    assert settings.paypal_base_url == "https://api-m.sandbox.paypal.com"
