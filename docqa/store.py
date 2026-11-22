"""Chroma vector store: embed chunks locally and run similarity search."""
from __future__ import annotations

from dataclasses import dataclass

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from .chunking import Chunk
from .config import settings


@dataclass
class Hit:
    id: str
    text: str
    metadata: dict
    distance: float


class VectorStore:
    """Thin wrapper over a persistent Chroma collection.

    Embeddings use Chroma's built-in all-MiniLM-L6-v2 (ONNX), which runs on CPU with no API key.
    """

    def __init__(self, path: str | None = None, collection: str | None = None):
        path = path or str(settings.data_dir / "chroma")
        self.client = chromadb.PersistentClient(path=path)
        self.collection = self.client.get_or_create_collection(
            name=collection or settings.collection,
            embedding_function=DefaultEmbeddingFunction(),
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, chunks: list[Chunk], batch: int = 128) -> int:
        for i in range(0, len(chunks), batch):
            part = chunks[i : i + batch]
            self.collection.upsert(
                ids=[c.id for c in part],
                documents=[c.text for c in part],
                metadatas=[c.metadata for c in part],
            )
        return len(chunks)

    def search(self, query: str, k: int | None = None, where: dict | None = None) -> list[Hit]:
        if self.count() == 0:
            return []
        k = min(k or settings.top_k, self.count())
        res = self.collection.query(query_texts=[query], n_results=k, where=where or None)
        return [
            Hit(id=i, text=d, metadata=m, distance=float(dist))
            for i, d, m, dist in zip(
                res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
            )
        ]

    def count(self) -> int:
        return self.collection.count()

    def sources(self, where: dict | None = None) -> list[str]:
        if self.count() == 0:
            return []
        metas = self.collection.get(where=where or None, include=["metadatas"])["metadatas"]
        return sorted({m["source"] for m in metas})

    def delete(self, where: dict) -> None:
        self.collection.delete(where=where)

    def reset(self) -> None:
        name = self.collection.name
        self.client.delete_collection(name)
        self.collection = self.client.get_or_create_collection(
            name=name, embedding_function=DefaultEmbeddingFunction(), metadata={"hnsw:space": "cosine"}
        )
