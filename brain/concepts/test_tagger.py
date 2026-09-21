from brain.concepts.tagger import CONCEPTS, tag_artifacts
from brain.loader.artifacts import FileArtifact, Symbol
from brain.reasoning.engine import Intent, IntentParser


def test_expanded_concepts():
    assert "queues" in CONCEPTS
    assert "secrets" in CONCEPTS


def test_tag_persistence():
    arts = [
        FileArtifact(
            path="internal/store/db.go",
            rel_path="internal/store/db.go",
            language="go",
            imports=["database/sql"],
            symbols=[Symbol(name="Open", kind="function", signature="func Open()")],
        )
    ]
    tags = tag_artifacts(arts)
    concepts = {t["concept"] for t in tags}
    assert "persistence" in concepts or "storage" in concepts


def test_intent_safest_place():
    p = IntentParser().parse("Where should I implement JWT refresh?")
    assert p.intent in {Intent.SAFEST_PLACE, Intent.WHERE_LIVES}
    assert p.concept in {"auth", None} or p.concept == "auth"


def test_intent_likely_break():
    p = IntentParser().parse("Which code is most likely to break?")
    assert p.intent == Intent.LIKELY_BREAK
