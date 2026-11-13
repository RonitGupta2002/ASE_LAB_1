"""Generate answers for the fixed dev sample or hidden test questions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from common.llm_client import LLMClient  # noqa: E402
from task3_rag.judge import stratified_sample  # noqa: E402
from task3_rag.pipeline import (  # noqa: E402
    CACHE_DIR,
    LOCAL_MODEL,
    RERANK_MODEL,
    add_metadata,
    cached_embeddings,
    load_jsonl,
    minmax,
    ranked_indices,
    recursive_chunk,
)

RESULTS_DIR = HERE / "results"
GENERATION_SYSTEM = """You are a precise PaderQueue documentation assistant.
Answer concisely using ONLY the provided context chunks; do not use outside knowledge.
Prefer official documentation (config, error, cli, changelog, runbook, incident) over forum posts.
Match exact PaderQueue versions (such as 1.x, 2.x, or 3.x); do not transfer facts across versions.
If the provided context does not contain the answer, reply with ONLY this exact string:
The documentation does not contain this information.
Return only the answer, with no preamble."""


def build_recursive_chunks(corpus: list[dict], size: int = 600) -> list[dict]:
    chunks = []
    for doc in corpus:
        for chunk_index, body in enumerate(recursive_chunk(doc.get("text", ""), size=size, overlap=100)):
            chunks.append({"doc_id": doc["doc_id"], "text": add_metadata({**doc, "text": body}),
                           "chunk_index": chunk_index})
    return chunks


def get_chunk_rankings(questions: list[dict], corpus: list[dict], config: str) -> tuple[list[list[int]], list[dict]]:
    from sentence_transformers import CrossEncoder, SentenceTransformer
    from rank_bm25 import BM25Okapi

    from task3_rag.pipeline import identifier_tokenize

    chunks = build_recursive_chunks(corpus)
    texts = [chunk["text"] for chunk in chunks]
    model = SentenceTransformer(LOCAL_MODEL)
    encode = lambda values: np.asarray(model.encode(values, convert_to_numpy=True), dtype=np.float32)  # noqa: E731
    vectors = cached_embeddings(texts, LOCAL_MODEL, encode)
    q_vectors = cached_embeddings([q["question"] for q in questions], LOCAL_MODEL, encode)

    bm25 = BM25Okapi([identifier_tokenize(text) for text in texts])
    reranker = CrossEncoder(RERANK_MODEL) if config == "r5" else None
    rankings = []
    for question, q_vector in zip(questions, q_vectors):
        dense_scores = vectors @ q_vector
        bm25_scores = np.asarray(bm25.get_scores(identifier_tokenize(question["question"])), dtype=np.float32)
        r4_scores = 0.5 * minmax(dense_scores) + 0.5 * minmax(bm25_scores)
        r4_order = ranked_indices(r4_scores).tolist()
        if config == "r4":
            rankings.append(r4_order)
            continue
        candidates = r4_order[:25]
        ce_scores = np.asarray(reranker.predict([
            (question["question"], chunks[idx]["text"]) for idx in candidates
        ]), dtype=np.float32)
        blended = 0.5 * minmax(r4_scores[candidates]) + 0.5 * minmax(ce_scores)
        rankings.append([candidates[i] for i in ranked_indices(blended).tolist()])
    return rankings, chunks


def top_unique_chunks(ranking: list[int], chunks: list[dict], k: int = 5) -> tuple[list[str], list[str]]:
    contexts, doc_ids, seen = [], [], set()
    for idx in ranking:
        chunk = chunks[idx]
        if chunk["doc_id"] in seen:
            continue
        seen.add(chunk["doc_id"])
        doc_ids.append(chunk["doc_id"])
        contexts.append(chunk["text"])
        if len(doc_ids) == k:
            break
    return contexts, doc_ids


def generate(questions: list[dict], config: str, log_path: Path, test_mode: bool = False) -> list[dict]:
    corpus = load_jsonl(HERE / "data" / "corpus.jsonl")
    rankings, chunks = get_chunk_rankings(questions, corpus, config)
    llm = LLMClient(model="openai.gpt-6-luna", log_path=log_path)
    rows = []
    for index, (question, ranking) in enumerate(zip(questions, rankings), start=1):
        contexts, doc_ids = top_unique_chunks(ranking, chunks, k=5)
        context_text = "\n\n--- CONTEXT CHUNK ---\n\n".join(contexts) or "(no retrieved context)"
        answer = llm.chat([
            {"role": "system", "content": GENERATION_SYSTEM},
            {"role": "user", "content": f"Question:\n{question['question']}\n\nContext chunks:\n{context_text}"},
        ])
        if test_mode:
            rows.append({"id": question["id"], "answer": answer, "retrieved_doc_ids": doc_ids})
        else:
            rows.append({"id": question["id"], "answer": answer, "contexts": contexts})
        print(f"[{index}/{len(questions)}] {question['id']}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=("r4", "r5"), required=True)
    parser.add_argument("--test", action="store_true", help="generate predictions for all test questions")
    args = parser.parse_args()
    if args.test:
        questions = load_jsonl(HERE / "data" / "questions_test.jsonl")
        destination = HERE / "predictions_test.jsonl"
        log_path = ROOT / "logs" / "gen_test.jsonl"
    else:
        questions = stratified_sample(load_jsonl(HERE / "data" / "questions_dev.jsonl"), 50, seed=0)
        destination = RESULTS_DIR / f"answers_{args.config}.jsonl"
        log_path = ROOT / "logs" / f"gen_{args.config}.jsonl"
    output = generate(questions, args.config, log_path, test_mode=args.test)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for row in output:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Saved {len(output)} rows to {destination}")


if __name__ == "__main__":
    main()
