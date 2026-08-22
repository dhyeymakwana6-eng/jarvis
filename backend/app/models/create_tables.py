from app.database.connection import engine
from app.database.base import Base

from app.models import User, Memory, Project, Goal, Conversation, Decision

Base.metadata.create_all(bind=engine)

print("All Jarvis tables created.")