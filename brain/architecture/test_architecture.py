from brain.architecture import infer_layer, safest_place_for_concept


def test_infer_layer():
    assert infer_layer("cmd/ncm-index/ncm-index.go") == "cmd"
    assert infer_layer("internal/logging/logging.go") == "internal"
    assert infer_layer("pkg/foo/bar.go") == "pkg"


def test_safest_place():
    tagged = [{"id": "internal/store/db.go", "label": "internal/store/db.go", "confidence": 0.8}]
    paths = ["cmd/main.go", "internal/store/db.go", "pkg/util/x.go"]
    result = safest_place_for_concept("persistence", tagged, paths)
    assert result["suggestion"]["path"] == "internal/store/db.go"
    assert result["suggestion"]["layer"] == "internal"
