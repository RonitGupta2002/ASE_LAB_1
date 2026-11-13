"""Print category metrics, a judge audit, and retrieval/generation failures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
QUESTIONS_DEV = HERE / "data" / "questions_dev.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def print_category_table() -> None:
    names = ["r1_bm25", "r2_fixed", "r3_s300", "r3_s600", "r3_s1200", "r4_hybrid", "r5_rerank"]
    categories = ["identifier", "paraphrase", "multi-hop", "version"]
    costs = json.loads((RESULTS / "cost_latency.json").read_text(encoding="utf-8"))["configurations"]
    print("\nPer-category retrieval (Recall@5 / Precision@5) and approximate tokens/query")
    print(f"{'Config':<14}{'identifier':>20}{'paraphrase':>20}{'multi-hop':>20}{'version':>20}{'tokens/query':>16}")
    for name in names:
        report = json.loads((RESULTS / f"metrics_{name}.json").read_text(encoding="utf-8"))["summary"]
        values = []
        for category in categories:
            scores = report["per_category"][category]
            values.append(f"{scores['context_recall']:.3f}/{scores['context_precision']:.3f}")
        token_name = "r3_recursive" if name == "r3_s600" else name
        tokens = costs[token_name]["approx_tokens_per_query_top5_chunks"]
        print(f"{name:<14}" + "".join(f"{value:>20}" for value in values) + f"{tokens:>16.1f}")


def print_judge_audit(config: str) -> None:
    judge_rows = load_jsonl(RESULTS / f"judge_{config}.jsonl")
    questions = {row["id"]: row for row in load_jsonl(QUESTIONS_DEV)}
    answers = {row["id"]: row for row in load_jsonl(RESULTS / f"answers_{config}.jsonl")}
    print(f"\nJudge audit: {config.upper()} (first 10 judged questions)")
    for result in judge_rows[:10]:
        question = questions[result["id"]]
        answer = answers[result["id"]]
        print(json.dumps({
            "id": result["id"],
            "category": question["category"],
            "question": question["question"],
            "ground_truth": question["answer"],
            "model_answer": answer["answer"],
            "faithfulness": result["faithfulness"],
            "answer_relevance": result["answer_relevance"],
            "correctness": result["correctness"],
            "correctness_reason": result["correctness_reason"],
        }, ensure_ascii=False, indent=2))

    retrieval_name = {"r4": "r4_hybrid", "r5": "r5_rerank"}[config]
    retrieval_rows = {row["id"]: row for row in load_jsonl(RESULTS / f"retrieval_{retrieval_name}.jsonl")}
    report = json.loads((RESULTS / f"metrics_{retrieval_name}.json").read_text(encoding="utf-8"))
    recall_by_id = {row["id"]: row["context_recall"] for row in report["per_question"]}
    failures = [row for row in judge_rows if float(row["correctness"]) < 1.0]
    failures.sort(key=lambda row: (float(row["correctness"]), row["id"]))
    print(f"\nFailure analysis: up to five {config.upper()} questions with correctness < 1.0")
    for result in failures[:5]:
        qid = result["id"]
        question = questions[qid]
        retrieved = retrieval_rows[qid]["retrieved_doc_ids"][:5]
        groups = question["relevant_doc_ids"]
        failure_type = "Retrieval Failure" if recall_by_id.get(qid, 0.0) < 1.0 else "Generation Failure"
        print(json.dumps({
            "id": qid,
            "category": question["category"],
            "question": question["question"],
            "ground_truth": question["answer"],
            "model_answer": answers[qid]["answer"],
            "correctness": result["correctness"],
            "correctness_reason": result["correctness_reason"],
            "context_recall@5": recall_by_id.get(qid, 0.0),
            "retrieved_doc_ids_top5": retrieved,
            "relevant_doc_id_groups": groups,
            "classification": failure_type,
        }, ensure_ascii=False, indent=2))
    if not failures:
        print("No questions in this judged set scored below 1.0 correctness.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=("r4", "r5"), default="r5")
    args = parser.parse_args()
    print_category_table()
    print_judge_audit(args.config)


if __name__ == "__main__":
    main()
