"""A small retrieval layer: chunk scraped pages, embed them, and retrieve the
most relevant chunks with stable source IDs (S1, S2, ...) the agents can cite."""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore

from usecase_forge.schemas import Source


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    """Split on paragraph boundaries into chunks of about `size` characters.

    The last `overlap` characters of a chunk are repeated at the start of the
    next one so a fact split across a boundary is still retrievable.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        while len(para) > size:  # hard-split very long paragraphs
            head, para = para[:size], para[size - overlap :]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        if current and len(current) + len(para) + 2 > size:
            chunks.append(current)
            current = current[-overlap:] + "\n\n" + para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


class KnowledgeBase:
    def __init__(self, embeddings: Embeddings):
        self._store = InMemoryVectorStore(embeddings)
        self._sources: dict[str, Source] = {}

    def __len__(self) -> int:
        return len(self._sources)

    def add_page(self, url: str, text: str) -> int:
        docs = []
        for chunk in chunk_text(text):
            source_id = f"S{len(self._sources) + 1}"
            self._sources[source_id] = Source(id=source_id, url=url, excerpt=chunk)
            docs.append(Document(page_content=chunk, metadata={"id": source_id, "url": url}))
        if docs:
            self._store.add_documents(docs)
        return len(docs)

    def retrieve(self, queries: list[str], k: int = 4) -> list[Source]:
        """Top-k chunks for each query, deduplicated, in first-seen order."""
        seen: dict[str, Source] = {}
        for query in queries:
            for doc in self._store.similarity_search(query, k=k):
                seen.setdefault(doc.metadata["id"], self._sources[doc.metadata["id"]])
        return list(seen.values())

    def source(self, source_id: str) -> Source | None:
        return self._sources.get(source_id)


def format_context(sources: list[Source]) -> str:
    return "\n\n".join(f"[{s.id}] ({s.url})\n{s.excerpt}" for s in sources)
