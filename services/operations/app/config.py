from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Operations runtime settings.

    Database persistence is intentionally opt-in so pure calculation endpoints
    can still run locally without a PostgreSQL instance. Production must set
    ``OPERATIONS_DATABASE_ENABLED=true`` before accepting Alertmanager traffic.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    operations_database_enabled: bool = False
    pghost: str = "192.168.0.8"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""
    pg_pool_min: int = 1
    pg_pool_max: int = 10
