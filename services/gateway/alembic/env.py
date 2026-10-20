from alembic import context
from sqlalchemy import create_engine

from shared.config import settings

engine = create_engine(settings().database_url)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
