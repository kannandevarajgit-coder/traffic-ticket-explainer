from docqa.agents import _ranked
from docqa.config import settings


def hit(source: str, distance: float) -> dict:
    return {"text": f"{source} {distance}", "metadata": {"source": source}, "distance": distance}


def test_big_document_cannot_crowd_out_a_small_one():
    hits = {f"m{i}": hit("manual.pdf", 0.40 + i / 100) for i in range(30)}
    hits["s"] = hit("points_table.txt", 0.55)  # worse than 15 manual passages
    ranked = _ranked(hits)
    limit = max(settings.top_k * 2, 8)
    assert len(ranked) == limit
    assert any(h["metadata"]["source"] == "points_table.txt" for h in ranked)
    assert [h["distance"] for h in ranked] == sorted(h["distance"] for h in ranked)


def test_single_document_still_fills_every_slot():
    hits = {f"m{i}": hit("manual.pdf", 0.40 + i / 100) for i in range(30)}
    assert len(_ranked(hits)) == max(settings.top_k * 2, 8)
