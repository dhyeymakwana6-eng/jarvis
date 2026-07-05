from app.database.connection import SessionLocal
from app.services.memory_extraction.pipeline import MemoryPipeline

db = SessionLocal()

pipeline = MemoryPipeline(db)

message = (
    "I am building Project D.0 Jarvis "
    "and I study Mechanical Engineering at PDEU."
)

result = pipeline.process_and_store(message)

print(result)

db.close()