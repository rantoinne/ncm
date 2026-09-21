from brain.embeddings.pipeline import embed_text, embed_texts, search_local


def test_embed_dim():
    v = embed_text("hello persistence store")
    assert len(v) == 64
    assert abs(sum(x * x for x in v) - 1.0) < 1e-5


def test_search_local():
    texts = {
        "a": embed_text("authentication jwt login"),
        "b": embed_text("database sql persistence"),
        "c": embed_text("unrelated astronomy"),
    }
    hits = search_local("where does auth live", texts, limit=2)
    assert hits
    assert hits[0]["id"] in {"a", "b"}
