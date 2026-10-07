from app.database.connection import engine, SessionLocal
from app.database.base import Base
from app.database.seed import ensure_default_user

from app.models import User, Memory, Project, Goal, Conversation, Decision

Base.metadata.create_all(bind=engine)

with SessionLocal() as db:
    ensure_default_user(db)

print("All Jarvis tables created.")
