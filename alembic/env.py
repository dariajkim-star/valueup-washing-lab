"""Alembic 마이그레이션 환경.

DB URL과 target metadata를 app 코드에서 주입한다(단일 진실원천 = app.config).
이 스토리는 빈 baseline이며, 실제 테이블 모델은 후속 스토리에서 app.models에 추가된다.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.models import Base

config = context.config
_db_url = settings.database_url.get_secret_value()
# configparser interpolation 회피: URL의 '%'(비밀번호 등)를 '%%'로 이스케이프
config.set_main_option("sqlalchemy.url", _db_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url,  # offline은 원문 URL 직접 사용
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
