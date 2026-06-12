#!/usr/bin/env python3
"""Resolve free-form text to the nearest YOLO COCO label."""
import sys

COCO_LABELS = tuple("person,bicycle,car,motorcycle,airplane,bus,train,truck,boat,traffic light,fire hydrant,stop sign,parking meter,bench,bird,cat,dog,horse,sheep,cow,elephant,bear,zebra,giraffe,backpack,umbrella,handbag,tie,suitcase,frisbee,skis,snowboard,sports ball,kite,baseball bat,baseball glove,skateboard,surfboard,tennis racket,bottle,wine glass,cup,fork,knife,spoon,bowl,banana,apple,sandwich,orange,broccoli,carrot,hot dog,pizza,donut,cake,chair,couch,potted plant,bed,dining table,toilet,tv,laptop,mouse,remote,keyboard,cell phone,microwave,oven,toaster,sink,refrigerator,book,clock,vase,scissors,teddy bear,hair drier,toothbrush".split(","))


class LabelResolver:
    def __init__(self, labels=COCO_LABELS, embedding_model="bge-micro"):
        self.labels = [labels[i] for i in sorted(labels)] if isinstance(labels, dict) else list(labels)
        self.exact = {label.lower(): label for label in self.labels}
        self.embedding_model = embedding_model
        self.encoder = self.label_embeddings = None

    @staticmethod
    def _norm(text):
        return " ".join(text.lower().replace("-", " ").replace("_", " ").split())

    def _ensure_encoder(self):
        if self.encoder is None:
            from mlx_embedding_models.embedding import EmbeddingModel
            self.encoder = EmbeddingModel.from_registry(self.embedding_model)
            label_texts = [f"a photo of a {label}" for label in self.labels]
            self.label_embeddings = self.encoder.encode(label_texts, show_progress=False)

    def _semantic(self, word):
        self._ensure_encoder()
        query = self.encoder.encode([f"a photo of a {word}"], show_progress=False)[0]
        scores = self.label_embeddings @ query
        idx = int(scores.argmax())
        return self.labels[idx], "mlx-embedding", round(float(scores[idx]), 3)

    def resolve(self, word):
        word = self._norm(word)
        if not word:
            raise ValueError("empty label")
        if word in self.exact:
            return self.exact[word], "exact", 1.0
        return self._semantic(word)


if __name__ == "__main__":
    word = " ".join(sys.argv[1:]).strip()
    if not word:
        raise SystemExit("usage: resolve_label.py WORD")
    print(LabelResolver().resolve(word)[0])
