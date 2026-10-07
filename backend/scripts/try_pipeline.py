"""
Manual check: runs the extraction pipeline on a sample message and
stores the result in the REAL database as the default user.
Run from backend/:  python -m scripts.try_pipeline
"""
from app.core.constants import DEFAULT_USER_ID
from app.database.connection import SessionLocal
from app.services.memory_extraction.pipeline import MemoryPipeline

db = SessionLocal()

pipeline = MemoryPipeline(db)

message = (
    "I am building Project D.0 Jarvis "
    "and I study Mechanical Engineering at PDEU."
)

result = pipeline.process_and_store(DEFAULT_USER_ID, message)

print(result)

db.close()