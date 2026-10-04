from ollama import embed


class EmbeddingError(Exception):
    pass


class EmbeddingService:

    MODEL = "nomic-embed-text"

    # nomic-embed-text is trained with task prefixes; using them
    # noticeably tightens query->memory distances. Stored memories
    # use the document prefix, search queries use the query prefix.
    DOCUMENT_PREFIX = "search_document: "
    QUERY_PREFIX = "search_query: "

    @staticmethod
    def _embed(text: str) -> list[float]:
        # Ollama raises ResponseError for model problems and
        # ConnectionError when the server isn't running.
        try:
            response = embed(
                model=EmbeddingService.MODEL,
                input=text
            )
        except Exception as error:
            raise EmbeddingError(
                f"Embedding generation failed ({EmbeddingService.MODEL}): {error}"
            ) from error

        return response.embeddings[0]

    @staticmethod
    def generate(text: str) -> list[float]:
        """Embedding for a memory to be stored."""
        return EmbeddingService._embed(EmbeddingService.DOCUMENT_PREFIX + text)

    @staticmethod
    def generate_query(text: str) -> list[float]:
        """Embedding for a search query."""
        return EmbeddingService._embed(EmbeddingService.QUERY_PREFIX + text)

    @staticmethod
    def try_generate(text: str) -> list[float] | None:
        """
        Like generate(), but returns None instead of raising, so a
        memory can still be saved while Ollama is down. Memories with
        no embedding are skipped by semantic search until re-embedded.
        """
        try:
            return EmbeddingService.generate(text)
        except EmbeddingError as error:
            print(f"WARNING: {error}")
            return None

    @staticmethod
    def try_generate_query(text: str) -> list[float] | None:
        try:
            return EmbeddingService.generate_query(text)
        except EmbeddingError as error:
            print(f"WARNING: {error}")
            return None
