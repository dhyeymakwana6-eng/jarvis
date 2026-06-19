from app.database.connection import engine
from app.database.base import Base

from app.models.user import User
from app.models.memory import Memory
from app.models.project import Project
from app.models.goal import Goal
from app.models.conversation import Conversation
from app.models.decision import Decision

Base.metadata.create_all(bind=engine)

print("All Jarvis tables created.")