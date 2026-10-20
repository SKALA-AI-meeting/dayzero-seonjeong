"""company-mcp: 회사별 인재상·사내 역량 평가 매뉴얼에서 행동과 관련된 조항을 찾는 읽기 전용 MCP 서버.

하나의 코드를 --company-dir만 바꿔 회사마다 띄운다(회사별 분기 없음). 회사 정보는 데이터 디렉터리의
company.json, 문서는 *.md에서 읽는다. 조항(###) 단위로 잘라 시작 시 메모리에 색인한다(문서가 작아 pgvector 불필요).

uv run python -m company_mcp.server --company-dir ../data/companies/<company> --port 9201
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import mcp_types as t
import uvicorn
from mcp.server.mcpserver import MCPServer

from shared.embedding import embed
from shared.mcp_common import READ, error, result

SECTION = re.compile(r"^###\s+(\S+)\s+(.+?)\s*$")
SENT = re.compile(r"(?<=[.!?다])\s+")
_index: dict = {"company": {}, "chunks": [], "vectors": [], "owner": []}

mcp = MCPServer(name="company-mcp", version="0.1.0",
                instructions="회사의 인재상·사내 역량 평가 매뉴얼에서 관찰된 행동과 관련된 조항을 찾는다. 읽기 전용. "
                             "조항 연결은 근거 첨부이며 좋다·나쁘다 판정이 아니다.")


def load(company_dir: Path) -> None:
    """company.json + *.md → 조항 청크. doc_id는 파일 이름(확장자 제외), section은 ### 다음 번호."""
    company = json.loads((company_dir / "company.json").read_text(encoding="utf-8"))
    chunks = []
    for md in sorted(company_dir.glob("*.md")):
        cur = None
        for line in md.read_text(encoding="utf-8").splitlines():
            m = SECTION.match(line)
            if m:
                cur = {"doc_id": md.stem, "section": m.group(1), "title": m.group(2), "lines": []}
                chunks.append(cur)
            elif line.startswith("#"):
                cur = None
            elif cur is not None:
                cur["lines"].append(line)
    texts, owner = [], []
    for i, ch in enumerate(chunks):
        ch["quote"] = "\n".join(ch.pop("lines")).strip()
        ch["grams"] = _grams(f"{ch['title']} {ch['quote']}")
        for part in [ch["title"], *[x for x in SENT.split(ch["quote"]) if x.strip()]]:  # 문장 단위 벡터 → 조항 점수는 최대값
            texts.append(f"{ch['title']}: {part}")
            owner.append(i)
    _index.update(company=company, chunks=chunks, vectors=embed(texts) if texts else [], owner=owner)


def _grams(text: str) -> set[str]:
    s = re.sub(r"[^0-9A-Za-z가-힣]", "", text)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def rank(query: str) -> list[tuple[float, int]]:
    """의미(문장 최대 코사인) 0.6 + 표현(글자 2-gram 중 질의가 조항에 겹치는 비율) 0.4."""
    qv, qg = embed([query])[0], _grams(query)
    sem = [0.0] * len(_index["chunks"])
    for v, i in zip(_index["vectors"], _index["owner"]):
        sem[i] = max(sem[i], sum(a * b for a, b in zip(qv, v)))
    lex = [len(qg & ch["grams"]) / max(1, len(qg)) for ch in _index["chunks"]]
    return sorted(((0.6 * s + 0.4 * w, i) for i, (s, w) in enumerate(zip(sem, lex))), reverse=True)


@mcp.tool(annotations=READ, description=(
    "이 회사의 인재상·역량 평가 매뉴얼에서 행동과 관련된 조항을 찾는다. query는 관찰된 행동 설명(1~400자), top_k 1~5. "
    "반환: company_id, company_name, doc_id, section, title, quote(조항 원문 그대로), score. "
    "조항 연결은 근거 첨부일 뿐 좋다·나쁘다 판정이 아니다. 오류: INVALID_ARGUMENT, INDEX_NOT_READY."))
async def search_criteria(query: str, top_k: int = 3) -> t.CallToolResult:
    if not query.strip() or len(query) > 400:
        return error("INVALID_ARGUMENT", "query는 1~400자입니다")
    if not 1 <= top_k <= 5:
        return error("INVALID_ARGUMENT", "top_k는 1~5입니다")
    if not _index["chunks"]:
        return error("INDEX_NOT_READY", "회사 문서가 색인되지 않았습니다")
    scored = rank(query)[:top_k]
    co = _index["company"]
    items = [{"company_id": co["company_id"], "company_name": co["name"], "doc_id": ch["doc_id"], "section": ch["section"],
              "title": ch["title"], "quote": ch["quote"], "score": round(s, 4), "uri": f"policy://{ch['doc_id']}#{ch['section']}"}
             for s, i in scored for ch in [_index["chunks"][i]]]
    return result({"ok": True, "data": {"items": items}, "error": None,
                   "citations": [{"uri": it["uri"], "title": it["title"]} for it in items]})


@mcp.resource("policy://{doc_id}#{section}", name="policy", mime_type="text/markdown",
              description="조항 원문. 예: policy://eval-manual#4.1")
def policy_resource(doc_id: str, section: str) -> str:
    ch = next((c for c in _index["chunks"] if c["doc_id"] == doc_id and c["section"] == section), None)
    if not ch:
        raise ValueError(f"NOT_FOUND: policy://{doc_id}#{section}")
    return f"# {_index['company']['name']} {doc_id} {ch['section']} {ch['title']}\n\n{ch['quote']}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company-dir", required=True)
    ap.add_argument("--port", type=int, default=9201)
    a = ap.parse_args()
    load(Path(a.company_dir).resolve())
    print(f"company-mcp {_index['company']['company_id']}: {len(_index['chunks'])}개 조항 색인 :{a.port}/mcp", flush=True)
    uvicorn.run(mcp.streamable_http_app(streamable_http_path="/mcp", host="0.0.0.0", stateless_http=True),
                host="0.0.0.0", port=a.port)


if __name__ == "__main__":
    main()
