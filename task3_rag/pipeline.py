"""Build and evaluate the Task 3 retrieval configurations.

Run from the repository root with ``uv run python task3_rag/pipeline.py``.
Pass ``--gateway-embed`` to use the configured gateway embedding model instead
of the local all-MiniLM-L6-v2 model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from common.llm_client import LLMClient, count_tokens  # noqa: E402

CORPUS_PATH = HERE / "data" / "corpus.jsonl"
QUESTIONS_PATH = HERE / "data" / "questions_dev.jsonl"
RESULTS_DIR = HERE / "results"
CACHE_DIR = HERE / ".cache"
LOCAL_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def save_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def add_metadata(doc: dict) -> str:
    return f"[{doc.get('type', '')} | title: {doc.get('title', '')} | version: {doc.get('version', '')}]\n{doc.get('text', '')}"


def fixed_chunk(text: str, size: int = 600, overlap: int = 100) -> list[str]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("size must be positive and overlap must be in [0, size)")
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def _split_on_separator(text: str, separator: str) -> list[str]:
    """Split while keeping each separator at the start of the following piece."""
    parts = re.split(f"({re.escape(separator)})", text)
    if len(parts) == 1:
        return [text]
    result = [parts[0]]
    for i in range(1, len(parts), 2):
        following = parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")
        if result[-1] == "":
            result[-1] = following
        else:
            result.append(following)
    return [part for part in result if part]


def _recursive_atoms(text: str, size: int, separators: tuple[str, ...]) -> list[str]:
    if len(text) <= size:
        return [text] if text else []
    for index, separator in enumerate(separators):
        pieces = _split_on_separator(text, separator)
        if len(pieces) == 1:
            continue
        atoms = []
        for piece in pieces:
            atoms.extend(_recursive_atoms(piece, size, separators[index + 1 :]))
        return atoms
    # An unusually long word (or text without any requested separator) still
    # needs to respect the requested maximum chunk length.
    return [text[i : i + size] for i in range(0, len(text), size)]


def recursive_chunk(
    text: str, size: int = 600, overlap: int = 100,
    separators: tuple[str, ...] = ("\n## ", "\n### ", "\n\n", "\n", ". ", " "),
) -> list[str]:
    """Recursively split on document structure, then merge with overlap."""
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("size must be positive and overlap must be in [0, size)")
    atoms = _recursive_atoms(text, size, separators)
    chunks: list[str] = []
    current = ""
    for atom in atoms:
        if not current or len(current) + len(atom) <= size:
            current += atom
            continue
        chunks.append(current)
        # Start the next chunk with the requested trailing context. If the next
        # atom is itself large, taking its suffix is handled by the next merge.
        current = current[-overlap:] + atom if overlap else atom
        if len(current) > size:
            # This can only happen when the overlap plus a full atom is too big.
            chunks.extend(fixed_chunk(current, size, overlap)[:-1])
            current = fixed_chunk(current, size, overlap)[-1]
    if current:
        chunks.append(current)
    # Merging a trailing atom with overlap can make a chunk too large; enforce
    # the cap without changing the fixed-size boundaries elsewhere.
    bounded = []
    for chunk in chunks:
        if len(chunk) <= size:
            bounded.append(chunk)
        else:
            bounded.extend(fixed_chunk(chunk, size, overlap))
    return bounded


def identifier_tokenize(text: str) -> list[str]:
    """Retain compounds (e.g. PQ-E4663) as well as their alphanumeric parts."""
    compounds = re.findall(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", text.lower())
    subtokens = [piece for compound in compounds for piece in re.findall(r"[a-z0-9]+", compound)]
    return compounds + subtokens


def normalized(vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-12)


def cached_embeddings(texts: list[str], model_name: str, encode: Callable[[list[str]], np.ndarray]) -> np.ndarray:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    digest.update(model_name.encode("utf-8"))
    for text in texts:
        digest.update(b"\0")
        digest.update(text.encode("utf-8"))
    cache_path = CACHE_DIR / f"embeddings_{digest.hexdigest()[:24]}.npy"
    if cache_path.exists():
        vectors = np.load(cache_path)
        if vectors.ndim == 2 and vectors.shape[0] == len(texts):
            return normalized(vectors)
    vectors = normalized(encode(texts))
    np.save(cache_path, vectors)
    return vectors


def minmax(values: np.ndarray) -> np.ndarray:
    low, high = float(np.min(values)), float(np.max(values))
    if high <= low:
        return np.zeros_like(values, dtype=np.float32)
    return ((values - low) / (high - low)).astype(np.float32)


def ranked_indices(scores: np.ndarray, limit: int | None = None) -> np.ndarray:
    # Stable sorting makes ties deterministic and preserves corpus order.
    order = np.argsort(-scores, kind="stable")
    return order if limit is None else order[:limit]


def mapped_results(questions: list[dict], chunks: list[dict], rankings: list[list[int]]) -> list[dict]:
    rows = []
    for question, ranking in zip(questions, rankings):
        doc_ids, seen = [], set()
        for idx in ranking:
            doc_id = chunks[idx]["doc_id"]
            if doc_id not in seen:
                seen.add(doc_id)
                doc_ids.append(doc_id)
        rows.append({"id": question["id"], "retrieved_doc_ids": doc_ids})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-embed", action="store_true", help="use LLMClient.embed rather than local MiniLM")
    parser.add_argument("--alpha", type=float, default=0.5, help="R4 weight for dense scores")
    args = parser.parse_args()
    if not 0 <= args.alpha <= 1:
        parser.error("--alpha must be between 0 and 1")

    corpus = load_jsonl(CORPUS_PATH)
    questions = load_jsonl(QUESTIONS_PATH)
    question_texts = [q["question"] for q in questions]
    llm = None
    st_model = None
    if args.gateway_embed:
        llm = LLMClient(log_path=HERE / "logs" / "retrieval_embeddings.jsonl")
        embed_fn = lambda texts: llm.embed(texts)  # noqa: E731
        embedding_name = llm.embedding_model or "gateway"
    else:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Local embeddings require `uv sync --extra local` or pass --gateway-embed") from exc
        st_model = SentenceTransformer(LOCAL_MODEL)
        embed_fn = lambda texts: np.asarray(st_model.encode(texts, convert_to_numpy=True), dtype=np.float32)  # noqa: E731
        embedding_name = LOCAL_MODEL

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cost_rows: dict[str, dict] = {}
    config_rankings: dict[str, list[list[int]]] = {}
    config_chunks: dict[str, list[dict]] = {}
    config_indexing: dict[str, float] = {}

    def build_chunks(method: str, size: int) -> list[dict]:
        splitter = fixed_chunk if method == "fixed" else recursive_chunk
        output = []
        for doc in corpus:
            header = f"[{doc.get('type', '')} | title: {doc.get('title', '')} | version: {doc.get('version', '')}]\n"
            for chunk_index, body in enumerate(splitter(doc.get("text", ""), size=size, overlap=100)):
                chunk_text = header + body
                output.append({"doc_id": doc["doc_id"], "text": chunk_text, "chunk_index": chunk_index})
        return output

    # The three R3 sizes are the shared base for R1, R3, R4, and R5.
    recursive_chunks: dict[int, list[dict]] = {}
    dense_vectors: dict[int, np.ndarray] = {}
    dense_query_vectors: dict[int, np.ndarray] = {}
    dense_build_times: dict[int, float] = {}
    for size in (300, 600, 1200):
        start = time.perf_counter()
        chunks = build_chunks("recursive", size)
        texts = [chunk["text"] for chunk in chunks]
        vectors = cached_embeddings(texts, embedding_name, embed_fn)
        dense_build_times[size] = time.perf_counter() - start
        recursive_chunks[size] = chunks
        dense_vectors[size] = vectors
        dense_query_vectors[size] = cached_embeddings(question_texts, embedding_name, embed_fn)

        retrieval_name = f"r3_s{size}"
        per_query_latency = []
        rankings = []
        for vector in dense_query_vectors[size]:
            query_start = time.perf_counter()
            scores = vectors @ vector
            rankings.append(ranked_indices(scores).tolist())
            per_query_latency.append((time.perf_counter() - query_start) * 1000)
        result_path = RESULTS_DIR / f"retrieval_{retrieval_name}.jsonl"
        save_jsonl(result_path, mapped_results(questions, chunks, rankings))
        config_rankings[retrieval_name] = rankings
        config_chunks[retrieval_name] = chunks
        config_indexing[retrieval_name] = dense_build_times[size]
        cost_rows[retrieval_name] = {
            "indexing_time_s": dense_build_times[size],
            "query_latency_ms_per_query": float(np.mean(per_query_latency)),
            "approx_tokens_per_query_top5_chunks": float(np.mean([
                sum(count_tokens(chunks[i]["text"]) for i in ranking[:5]) for ranking in rankings
            ])),
            "n_chunks": len(chunks),
        }

    # Alias the required R3 system to the size-600 study run.
    config_rankings["r3_recursive"] = config_rankings["r3_s600"]
    config_chunks["r3_recursive"] = recursive_chunks[600]
    config_indexing["r3_recursive"] = config_indexing["r3_s600"]
    cost_rows["r3_recursive"] = dict(cost_rows["r3_s600"])

    # R1 BM25, using exactly the R3 size-600 chunks.
    from rank_bm25 import BM25Okapi

    start = time.perf_counter()
    bm25_chunks = recursive_chunks[600]
    bm25 = BM25Okapi([identifier_tokenize(chunk["text"]) for chunk in bm25_chunks])
    bm25_indexing = time.perf_counter() - start
    bm25_rankings, bm25_latency = [], []
    bm25_scores_all = []
    for question in questions:
        query_start = time.perf_counter()
        scores = np.asarray(bm25.get_scores(identifier_tokenize(question["question"])), dtype=np.float32)
        ranking = ranked_indices(scores).tolist()
        bm25_rankings.append(ranking)
        bm25_scores_all.append(scores)
        bm25_latency.append((time.perf_counter() - query_start) * 1000)
    config_rankings["r1_bm25"] = bm25_rankings
    config_chunks["r1_bm25"] = bm25_chunks
    config_indexing["r1_bm25"] = bm25_indexing
    save_jsonl(RESULTS_DIR / "retrieval_r1_bm25.jsonl", mapped_results(questions, bm25_chunks, bm25_rankings))
    cost_rows["r1_bm25"] = {
        "indexing_time_s": bm25_indexing,
        "query_latency_ms_per_query": float(np.mean(bm25_latency)),
        "approx_tokens_per_query_top5_chunks": float(np.mean([
            sum(count_tokens(bm25_chunks[i]["text"]) for i in ranking[:5]) for ranking in bm25_rankings
        ])),
        "n_chunks": len(bm25_chunks),
    }

    # R2 fixed-size chunks + dense embeddings.
    start = time.perf_counter()
    fixed_chunks = build_chunks("fixed", 600)
    fixed_vectors = cached_embeddings([chunk["text"] for chunk in fixed_chunks], embedding_name, embed_fn)
    fixed_indexing = time.perf_counter() - start
    fixed_rankings, fixed_latency = [], []
    for vector in dense_query_vectors[600]:
        query_start = time.perf_counter()
        ranking = ranked_indices(fixed_vectors @ vector).tolist()
        fixed_rankings.append(ranking)
        fixed_latency.append((time.perf_counter() - query_start) * 1000)
    config_rankings["r2_fixed"] = fixed_rankings
    config_chunks["r2_fixed"] = fixed_chunks
    config_indexing["r2_fixed"] = fixed_indexing
    save_jsonl(RESULTS_DIR / "retrieval_r2_fixed.jsonl", mapped_results(questions, fixed_chunks, fixed_rankings))
    cost_rows["r2_fixed"] = {
        "indexing_time_s": fixed_indexing,
        "query_latency_ms_per_query": float(np.mean(fixed_latency)),
        "approx_tokens_per_query_top5_chunks": float(np.mean([
            sum(count_tokens(fixed_chunks[i]["text"]) for i in ranking[:5]) for ranking in fixed_rankings
        ])),
        "n_chunks": len(fixed_chunks),
    }

    # R4 min-max score fusion, evaluated across the complete shared R3 index.
    hybrid_rankings, hybrid_latency, hybrid_scores_all = [], [], []
    for q_idx, vector in enumerate(dense_query_vectors[600]):
        query_start = time.perf_counter()
        dense_scores = dense_vectors[600] @ vector
        hybrid_scores = args.alpha * minmax(dense_scores) + (1 - args.alpha) * minmax(bm25_scores_all[q_idx])
        hybrid_rankings.append(ranked_indices(hybrid_scores).tolist())
        hybrid_scores_all.append(hybrid_scores)
        hybrid_latency.append((time.perf_counter() - query_start) * 1000)
    config_rankings["r4_hybrid"] = hybrid_rankings
    config_chunks["r4_hybrid"] = recursive_chunks[600]
    config_indexing["r4_hybrid"] = dense_build_times[600] + bm25_indexing
    save_jsonl(RESULTS_DIR / "retrieval_r4_hybrid.jsonl", mapped_results(questions, recursive_chunks[600], hybrid_rankings))
    cost_rows["r4_hybrid"] = {
        "indexing_time_s": config_indexing["r4_hybrid"],
        "query_latency_ms_per_query": float(np.mean(hybrid_latency)),
        "approx_tokens_per_query_top5_chunks": float(np.mean([
            sum(count_tokens(recursive_chunks[600][i]["text"]) for i in ranking[:5]) for ranking in hybrid_rankings
        ])),
        "n_chunks": len(recursive_chunks[600]),
    }

    # R5 reranks the top 25 R4 chunks per question, blending the normalized
    # cross-encoder score with the R4 score to retain the hybrid signal.
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise RuntimeError("R5 requires sentence-transformers; install with `uv sync --extra local`") from exc
    reranker = CrossEncoder(RERANK_MODEL)
    rerank_rankings, rerank_latency = [], []
    for q_idx, question in enumerate(questions):
        query_start = time.perf_counter()
        candidates = hybrid_rankings[q_idx][:25]
        pairs = [(question["question"], recursive_chunks[600][idx]["text"]) for idx in candidates]
        scores = np.asarray(reranker.predict(pairs), dtype=np.float32)
        r4_candidate_scores = minmax(hybrid_scores_all[q_idx][candidates])
        blended_scores = 0.5 * r4_candidate_scores + 0.5 * minmax(scores)
        rerank_rankings.append([candidates[i] for i in ranked_indices(blended_scores).tolist()])
        rerank_latency.append((time.perf_counter() - query_start) * 1000)
    config_rankings["r5_rerank"] = rerank_rankings
    config_chunks["r5_rerank"] = recursive_chunks[600]
    config_indexing["r5_rerank"] = config_indexing["r4_hybrid"]
    save_jsonl(RESULTS_DIR / "retrieval_r5_rerank.jsonl", mapped_results(questions, recursive_chunks[600], rerank_rankings))
    cost_rows["r5_rerank"] = {
        "indexing_time_s": config_indexing["r5_rerank"],
        "query_latency_ms_per_query": float(np.mean(rerank_latency)),
        "approx_tokens_per_query_top5_chunks": float(np.mean([
            sum(count_tokens(recursive_chunks[600][i]["text"]) for i in ranking[:5]) for ranking in rerank_rankings
        ])),
        "n_chunks": len(recursive_chunks[600]),
        "rerank_candidates": 25,
    }

    # Store the named R3 result in addition to the requested chunk-study file.
    save_jsonl(RESULTS_DIR / "retrieval_r3_recursive.jsonl", mapped_results(questions, recursive_chunks[600], config_rankings["r3_recursive"]))

    # Evaluate every requested output through the supplied evaluator CLI.
    evaluator_runs = [
        ("r1_bm25", "retrieval_r1_bm25.jsonl"),
        ("r2_fixed", "retrieval_r2_fixed.jsonl"),
        ("r3_recursive", "retrieval_r3_recursive.jsonl"),
        ("r4_hybrid", "retrieval_r4_hybrid.jsonl"),
        ("r5_rerank", "retrieval_r5_rerank.jsonl"),
        *((f"r3_s{size}", f"retrieval_r3_s{size}.jsonl") for size in (300, 600, 1200)),
    ]
    for name, filename in evaluator_runs:
        subprocess.run(
            [sys.executable, str(HERE / "evaluate.py"), str(RESULTS_DIR / filename), "--k", "5", "--json", str(RESULTS_DIR / f"metrics_{name}.json")],
            check=True,
        )

    cost_path = RESULTS_DIR / "cost_latency.json"
    cost_path.write_text(json.dumps({
        "latency_scope": "retrieval scoring per question; query vectors are embedded/cached before timing",
        "embedding_model": embedding_name,
        "configurations": cost_rows,
    }, indent=2), encoding="utf-8")

    print("\nComparison (k=5; metrics on answerable dev questions)")
    print(f"{'Configuration':<18}{'Recall@5':>11}{'Precision@5':>13}{'Index s':>12}{'Latency ms':>13}")
    order = ["r1_bm25", "r2_fixed", "r3_recursive", "r4_hybrid", "r5_rerank", "r3_s300", "r3_s600", "r3_s1200"]
    for name in order:
        metrics = json.loads((RESULTS_DIR / f"metrics_{name}.json").read_text(encoding="utf-8"))["summary"]["overall"]
        cost = cost_rows[name]
        print(f"{name:<18}{metrics['context_recall']:>11.3f}{metrics['context_precision']:>13.3f}"
              f"{cost['indexing_time_s']:>12.3f}{cost['query_latency_ms_per_query']:>13.3f}")
    print(f"\nSaved metrics and retrievals under {RESULTS_DIR}")
    print(f"Saved cost/latency details to {cost_path}")


if __name__ == "__main__":
    main()
