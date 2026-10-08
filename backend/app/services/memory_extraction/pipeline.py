from sqlalchemy.orm import Session

from app.crud.memory import create_memory, update_memory, supersede_memory
from app.database.connection import SessionLocal
from app.models.conversation import Conversation
from app.services.embedding_service import EmbeddingService
from app.services.profile_service import ProfileService
from app.services.tracking_service import TrackingService
from app.services.agent_service import TASK_TOOLS
from .conflict_checker import ConflictChecker
from .extractor import MemoryExtractor
from .classifier import MemoryClassifier
from .scorer import MemoryScorer
from .deduplicator import MemoryDeduplicator, DeduplicationDecision


class MemoryPipeline:
    """
    Coordinates memory extraction processing.
    """

    def __init__(self, db: Session, detect_conflicts: bool = True):
        self.db = db

        self.extractor = MemoryExtractor()
        self.classifier = MemoryClassifier()
        self.scorer = MemoryScorer()
        self.deduplicator = MemoryDeduplicator(
            ConflictChecker() if detect_conflicts else None
        )

    def process(self, user_id: int, message: str):
        candidates = self.extractor.extract(message)

        memories = []

        for candidate in candidates:
            memory_type = self.classifier.classify(candidate)
            importance = self.scorer.score(candidate)

            memory_data = {
                "content": candidate,
                "category": memory_type,
                "importance": importance,
            }

            # Embedded once here and reused for dedup and storage.
            embedding = EmbeddingService.try_generate(candidate)

            deduplication_result = self.deduplicator.process(
                self.db,
                user_id,
                memory_data,
                embedding
            )

            memory_data["embedding"] = embedding

            memory_data["deduplication"] = (
                deduplication_result.model_dump()
            )

            memories.append(memory_data)

        return memories

    def process_and_store(self, user_id: int, message: str):
        memories = self.process(user_id, message)

        stored_memories = []

        for memory in memories:
            decision = memory["deduplication"]["decision"]
            importance_scaled = int(memory["importance"] * 100)

            # SIMILAR means "related but possibly a different fact"
            # (e.g. a new employer), so it's stored rather than dropped.
            if decision in (
                DeduplicationDecision.NEW,
                DeduplicationDecision.SIMILAR
            ):
                stored = create_memory(
                    db=self.db,
                    user_id=user_id,
                    category=memory["category"],
                    content=memory["content"],
                    importance=importance_scaled,
                    embedding=memory["embedding"]
                )
                stored_memories.append(stored)

            elif decision == DeduplicationDecision.UPDATE:
                existing_id = memory["deduplication"]["existing_memory_id"]
                stored = update_memory(
                    db=self.db,
                    user_id=user_id,
                    memory_id=existing_id,
                    category=memory["category"],
                    content=memory["content"],
                    importance=importance_scaled,
                    embedding=memory["embedding"]
                )
                stored_memories.append(stored)

            # CONFLICT: the newer statement wins. Store it and retire
            # the contradicted memory (soft-deleted, restorable).
            elif decision == DeduplicationDecision.CONFLICT:
                stored = create_memory(
                    db=self.db,
                    user_id=user_id,
                    category=memory["category"],
                    content=memory["content"],
                    importance=importance_scaled,
                    embedding=memory["embedding"]
                )
                supersede_memory(
                    self.db,
                    user_id,
                    memory["deduplication"]["existing_memory_id"],
                    stored.id
                )
                stored_memories.append(stored)

            # DUPLICATE: already stored, nothing to do.

        return stored_memories

    @staticmethod
    def process_conversation(conversation_id: int):
        """
        Background-task entry point for /chat: memory extraction (with
        LLM conflict checks) and project/goal tracking take seconds, so
        they run after the response is sent. Opens its own session because the request's session
        is closed by then. The conversation is only marked processed
        on success, so a crash, restart or LLM outage leaves it for
        process_pending() to retry at the next startup.
        """
        db = SessionLocal()

        try:
            conversation = db.get(Conversation, conversation_id)

            if conversation is None or conversation.memories_processed:
                return

            user_id = conversation.user_id

            MemoryPipeline(db).process_and_store(
                user_id,
                conversation.user_message
            )

            # Projects/goals stated in the message ("I finished X",
            # "I want to do Y by Friday").
            # Tasks too: a safety net for changes the chat agent missed
            # (or claimed without a tool call). If it did act on tasks,
            # the tracker skips new tasks and the ones it touched.
            task_actions = [
                action for action in conversation.actions or []
                if action.get("tool") in TASK_TOOLS
            ]
            TrackingService.process_message(
                db,
                user_id,
                conversation.user_message,
                agent_task_ids={
                    action["task_id"] for action in task_actions if action.get("task_id")
                } if task_actions else None
            )

            conversation.memories_processed = True
            db.commit()
        except Exception as error:
            print(
                f"WARNING: memory extraction failed for conversation "
                f"{conversation_id}: {error}"
            )
            db.rollback()
            return
        finally:
            db.close()

        ProfileService.refresh_if_stale(user_id)

    @staticmethod
    def process_pending():
        """
        Runs extraction for conversations left unprocessed (e.g. the
        server stopped mid-task). Called once at startup.
        """
        db = SessionLocal()

        try:
            pending_ids = [
                conversation_id
                for (conversation_id,) in (
                    db.query(Conversation.id)
                    .filter(Conversation.memories_processed == False)
                    .order_by(Conversation.id)
                    .all()
                )
            ]
        finally:
            db.close()

        if pending_ids:
            print(f"Processing {len(pending_ids)} pending conversation(s).")

        for conversation_id in pending_ids:
            MemoryPipeline.process_conversation(conversation_id)
