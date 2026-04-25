from __future__ import annotations

from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimension: int | None
    normalize: bool

    def encode(self, texts: list[str]) -> list[list[float]]:
        ...


class NullEmbedder:
    model_name = "none"
    dimension = 0
    normalize = False

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-large-zh-v1.5", normalize: bool = True, batch_size: int = 16):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.normalize = normalize
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name)
        self.dimension = int(self.model.get_sentence_embedding_dimension())

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize,
            show_progress_bar=True,
        )
        return [[float(x) for x in row] for row in vectors]

