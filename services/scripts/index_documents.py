"""Offline indexer: documents → tokenizer chunks (≤96 tokens, overlap ≤16) → local embedding → pgvector.

Uses INDEXER_DATABASE_URL (chunk writer role). Never run by the online rag-mcp process.
"""
from __future__ import annotations

import argparse

from pgvector.psycopg import register_vector

from shared.config import SCENARIO_ID, settings
from shared.db import J, all_, tx
from shared.embedding import embed, model, model_revision

MAX_TOKENS = 96
OVERLAP = 16


def chunk(body: str, tokenizer) -> list[tuple[int, int, str]]:
    """Split by paragraph, then sliding token windows. Returns (char_start, char_end, text) of the original body."""
    out: list[tuple[int, int, str]] = []
    pos = 0
    for para in body.split("\n\n"):
        start = body.index(para, pos) if para else pos
        pos = start + len(para)
        text = para.strip()
        if not text:
            continue
        lead = para.index(text)
        base = start + lead
        enc = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        offs = enc["offset_mapping"]
        i = 0
        while i < len(offs):
            j = min(i + MAX_TOKENS, len(offs))
            cs, ce = offs[i][0], offs[j - 1][1]
            piece = text[cs:ce]
            assert len(tokenizer(piece)["input_ids"]) <= 128, "모델 입력 상한 초과"
            out.append((base + cs, base + ce, piece))
            if j == len(offs):
                break
            i = j - OVERLAP
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=SCENARIO_ID)
    a = ap.parse_args()
    s = settings()
    m = model(allow_download=True)
    tok = m.tokenizer
    rev = model_revision(m)
    dsn = s.indexer_database_url or s.psycopg_dsn
    with tx(dsn) as c:
        register_vector(c)
        docs = all_(c, "SELECT id, version, title, body, keywords FROM documents WHERE scenario_id=%s ORDER BY id", (a.scenario,))
        total = 0
        for d in docs:
            pieces = chunk(d["body"], tok)
            # Model-side representation = title + chunk; the stored/quoted body stays the exact original substring.
            reprs = [f"{d['title']}: {p[2]}" for p in pieces]
            assert all(len(tok(r)["input_ids"]) <= 128 for r in reprs), "모델 입력 상한 초과"
            vecs = embed(reprs)
            c.execute("DELETE FROM document_chunks WHERE document_id=%s AND index_version=%s", (d["id"], s.index_version))
            for n, ((cs, ce, text), v) in enumerate(zip(pieces, vecs)):
                assert d["body"][cs:ce] == text
                c.execute("""INSERT INTO document_chunks(id,document_id,document_version,ordinal,body,char_start,char_end,
                             keywords,embedding,embedding_model,embedding_revision,embedding_dimension,index_version)
                             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s,%s,%s)""",
                          (f"{d['id']}:v{d['version']}:{n}", d["id"], d["version"], n, text, cs, ce, J(d["keywords"]),
                           str(v), s.embedding_model, rev, len(v), s.index_version))
            total += len(pieces)
            print(f"{d['id']}: {len(pieces)} chunks")
    print(f"색인 완료: 문서 {len(docs)}개, 청크 {total}개, model={s.embedding_model}, revision={rev}, "
          f"dim={s.embedding_dimension}, index_version={s.index_version}")


if __name__ == "__main__":
    main()
