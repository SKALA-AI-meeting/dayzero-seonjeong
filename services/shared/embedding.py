"""Local SentenceTransformer embedding (CPU, normalized). Never downloads at query time."""
from __future__ import annotations

import os
from functools import lru_cache

from shared.config import ROOT, settings

os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "hf"))
if not os.path.isabs(os.environ["HF_HOME"]):
    os.environ["HF_HOME"] = str((ROOT / "services" / os.environ["HF_HOME"]).resolve())


@lru_cache
def model(allow_download: bool = False):
    if not allow_download:
        os.environ["HF_HUB_OFFLINE"] = "1"
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings().embedding_model, device="cpu")


def model_revision(m) -> str:
    ref = os.path.join(os.environ["HF_HOME"], "hub", "models--" + settings().embedding_model.replace("/", "--"),
                       "refs", "main")
    if os.path.exists(ref):
        return open(ref).read().strip()
    try:
        cfg = m[0].auto_model.config
        return str(getattr(cfg, "_commit_hash", None) or getattr(cfg, "_name_or_path", "unknown"))
    except Exception:
        return "unknown"


def embed(texts: list[str], allow_download: bool = False) -> list[list[float]]:
    vecs = model(allow_download).encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return [v.tolist() for v in vecs]
