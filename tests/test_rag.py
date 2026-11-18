from langchain_core.embeddings import DeterministicFakeEmbedding

from usecase_forge.rag import KnowledgeBase, chunk_text, format_context


def test_chunks_respect_size_and_keep_all_text():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 40 for i in range(20))
    chunks = chunk_text(text, size=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 500 + 50 + 2 for c in chunks)
    for i in range(20):
        assert any(f"Paragraph {i} " in c for c in chunks)


def test_long_paragraph_is_hard_split():
    chunks = chunk_text("x" * 2000, size=500, overlap=100)
    assert all(len(c) <= 500 for c in chunks)
    assert len(chunks) >= 4


def test_empty_text_gives_no_chunks():
    assert chunk_text("   \n\n  ") == []


def test_knowledge_base_ids_are_sequential_across_pages():
    kb = KnowledgeBase(DeterministicFakeEmbedding(size=16))
    kb.add_page("https://a.com", "alpha " * 300)
    kb.add_page("https://b.com", "beta " * 50)
    assert kb.source("S1").url == "https://a.com"
    assert kb.source(f"S{len(kb)}").url == "https://b.com"


def test_retrieve_deduplicates_and_formats_with_ids():
    kb = KnowledgeBase(DeterministicFakeEmbedding(size=16))
    kb.add_page("https://a.com", "\n\n".join(f"fact number {i}" for i in range(5)))
    hits = kb.retrieve(["fact", "fact"], k=3)
    assert len(hits) == len({h.id for h in hits})
    assert format_context(hits).startswith(f"[{hits[0].id}] (https://a.com)")
