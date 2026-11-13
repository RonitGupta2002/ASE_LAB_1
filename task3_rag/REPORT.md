# Task 3 — Retrieval-Augmented Generation: Experimental Report

## Executive summary

We evaluated retrieval at `k=5` on the 120 answerable development questions (30 each in `identifier`, `paraphrase`, `multi-hop`, and `version`). R5, hybrid retrieval followed by cross-encoder reranking, has the strongest measured retrieval result: Recall@5 **0.613** and Precision@5 **0.599**. R4 hybrid is close at **0.583 / 0.561** and is dramatically faster at retrieval time (**0.31 ms/query** versus **2,659 ms/query** for R5). On the 50-question end-to-end judge sample, correctness is **0.71 for R5** and **0.66 for R4**. Considering that modest quality gain against the reranker latency, we recommend deploying **R4 hybrid, recursive 600-character chunks, `alpha=0.5`**, and treating R5 as a quality-oriented option when roughly 2.7 seconds of retrieval latency is acceptable.

## 1. Retrieval evaluation

Recall and precision are reported from `results/metrics_*.json`; values are means over the 120 answerable questions. Each category contains 30 questions. Category table cells show **Recall@5 / Precision@5**. The `R3` row is the 600-character recursive-chunk configuration (`R3-600`).

| System | Overall R@5 / P@5 | `identifier` R/P | `paraphrase` R/P | `multi-hop` R/P | `version` R/P |
|---|---:|---:|---:|---:|---:|
| R1 — BM25, identifier-aware tokens | 0.533 / 0.558 | 0.900 / 0.744 | 0.133 / 0.028 | 0.467 / 0.824 | 0.633 / 0.633 |
| R2 — dense, fixed 600 | 0.342 / 0.266 | 0.567 / 0.528 | 0.367 / 0.272 | 0.033 / 0.042 | 0.400 / 0.222 |
| R3 — dense, recursive 600 | 0.350 / 0.260 | 0.533 / 0.517 | 0.433 / 0.269 | 0.033 / 0.040 | 0.400 / 0.215 |
| R3 — recursive 300 | 0.467 / 0.385 | 0.567 / 0.498 | 0.600 / 0.427 | 0.067 / 0.073 | 0.633 / 0.543 |
| R3 — recursive 600 | 0.350 / 0.260 | 0.533 / 0.517 | 0.433 / 0.269 | 0.033 / 0.040 | 0.400 / 0.215 |
| R3 — recursive 1200 | 0.354 / 0.275 | 0.533 / 0.469 | 0.400 / 0.311 | 0.017 / 0.033 | 0.467 / 0.287 |
| R4 — hybrid, recursive 600 | 0.583 / 0.561 | 0.800 / 0.694 | 0.467 / 0.222 | 0.433 / 0.746 | 0.633 / 0.583 |
| R5 — R4 plus cross-encoder reranking | **0.613 / 0.599** | 0.767 / 0.651 | **0.600 / 0.364** | **0.450 / 0.754** | 0.633 / **0.628** |

**What the category results show.** BM25 is particularly effective on literal identifiers (0.900 recall) and multi-hop queries that contain distinctive terms, but performs poorly on paraphrases (0.133 recall). Dense retrieval helps paraphrases, while R4’s fusion sharply improves multi-hop retrieval over either dense baseline. R5 improves overall recall and precision relative to R4, with the largest recall gain in paraphrases (+0.133); R4 retains a small lead on identifier recall (+0.033). Unanswerable questions are excluded from retrieval metrics because they have no relevant documents.

### R4 hybrid weight and score normalization

The recorded R4 default is **`alpha=0.5`** (`pipeline.py`, default argument). For each query, the system independently min-max normalizes dense cosine scores and BM25 scores over the shared R3-600 chunk index, then combines them as:

`hybrid_score = 0.5 × minmax(dense_score) + 0.5 × minmax(BM25_score)`

The equal weight gives lexical matching and semantic matching equal influence after putting their different raw score ranges on a common `[0, 1]` scale. That is especially suitable here: exact identifiers and error codes benefit from BM25, while paraphrases benefit from embeddings. Per-query min-max normalization prevents the numerically larger raw BM25 or cosine range from dominating simply because of scale. If a score vector is constant, the implementation maps it to zeros rather than dividing by zero. The recorded artifacts establish the default and its strong results (Recall@5 0.583 versus 0.533 for BM25 and 0.350 for dense recursive 600); they do **not** record an alpha sweep, so we present 0.5 as a transparent balanced choice, not as a proven optimum.

## 2. Chunk-size comparison: R3, recursive chunks

| Chunk size | Overall R@5 | Overall P@5 | Paraphrase R@5 | Version R@5 | Top-5 context tokens/query (approx.) | Dense scoring latency (ms/query) |
|---:|---:|---:|---:|---:|---:|---:|
| 300 | **0.467** | **0.385** | **0.600** | **0.633** | **379** | 0.750 |
| 600 | 0.350 | 0.260 | 0.433 | 0.400 | 618 | 0.340 |
| 1200 | 0.354 | 0.275 | 0.400 | 0.467 | 756 | **0.207** |

The 300-character setting wins clearly on overall retrieval quality: its recall is 0.117 higher than 600 and 0.113 higher than 1200, and its precision is also highest. It also uses the fewest retrieved-context tokens. This fits the PaderQueue corpus: many answers live in compact, highly specific configuration, error, or CLI passages. With the local `sentence-transformers/all-MiniLM-L6-v2` encoder, shorter recursive chunks create tighter semantic units, so the embedding is less likely to be diluted by neighboring settings or unrelated details. The improvements are especially visible for paraphrases (0.600 versus 0.433 / 0.400 recall) and versions (0.633 versus 0.400 / 0.467). Larger chunks have fewer vectors and therefore slightly faster dense scoring, but that speed advantage does not compensate for weaker retrieval quality and more prompt context. The 300-character index has more chunks (3,029 versus 1,220 and 958), so its indexing time is higher.

## 3. Cost and latency

Retrieval measurements are from `results/cost_latency.json`. Indexing and retrieval timings are the recorded local timings; query vectors are embedded/cached before retrieval timing. Prompt-token estimates in this table are the approximate token count for the five retrieved chunks. Separately, the generation log reports the actual mean prompt tokens submitted for the answer-generation requests. LLM costs below are totals from the corresponding repository-level `logs/` files, which cover the 50 answer/judge queries in the end-to-end evaluation sample.

| Configuration | Indexing time (s) | Retrieval latency (ms/query) | Approx. top-5 context tokens/query | Mean generation prompt tokens/query | Generation cost (50 queries) | Judge cost (50 questions) |
|---|---:|---:|---:|---:|---:|---:|
| R1 — BM25 | 0.212 | 15.223 | 640 | — | — | — |
| R2 — dense fixed 600 | 0.027 | 0.381 | 639 | — | — | — |
| R3 — recursive 300 | 0.046 | 0.750 | 379 | — | — | — |
| R3 — recursive 600 | 0.025 | 0.340 | 618 | — | — | — |
| R3 — recursive 1200 | 0.022 | 0.207 | 756 | — | — | — |
| R4 — hybrid 600 | 0.236 | 0.308 | 606 | 769 | $0.004901 (≈$0.000098/query) | $0.007760 (≈$0.000155/question) |
| R5 — hybrid + reranker | 0.236 | 2,659.381 | 615 | 794 | $0.005287 (≈$0.000106/query) | $0.008133 (≈$0.000163/question) |

Generation costs come from `logs/gen_r4.jsonl` and `logs/gen_r5.jsonl`; judge costs come from `logs/judge_answers_r4.jsonl` and `logs/judge_answers_r5.jsonl`. The judge made 124 calls for R4 and 127 for R5; counts can exceed the number of questions because each non-abstained answer is evaluated on multiple dimensions and some calls are retried. These are observed run costs, not an extrapolated provider price. Approximate end-to-end LLM spend for the 50-question sample is generation plus judging: **$0.012661 for R4** and **$0.013419 for R5**. The particularly large R5 query-latency figure includes cross-encoder scoring of up to 25 candidates; it is not generation latency.

## 4. End-to-end evaluation: R4 versus R5

`judge.py` evaluated the same deterministic, stratified 50-question sample: 10 questions in each of the five dataset categories. Correctness is scored 1 (correct), 0.5 (partial), or 0 (wrong). Faithfulness is averaged only over answers with factual claims; abstentions have no faithfulness score. Answer relevance is the judge’s embedding-based measure of how well an answer addresses its question. The table shows category means; abstention is the fraction of questions abstained on.

| System | Category (n=10) | Abstained | Faithfulness | Answer relevance | Correctness |
|---|---|---:|---:|---:|---:|
| R4 | identifier | 0.50 | 1.000 | 0.399 | 0.500 |
| R4 | paraphrase | 0.10 | 1.000 | 0.399 | 0.900 |
| R4 | multi-hop | 1.00 | — | 0.188 | 0.000 |
| R4 | version | 0.10 | 0.889 | 0.439 | 0.900 |
| R4 | unanswerable | 1.00 | — | 0.104 | 1.000 |
| **R4** | **overall (n=50)** | **0.54** | **0.957** | **0.306** | **0.660** |
| R5 | identifier | 0.30 | 1.000 | 0.434 | 0.650 |
| R5 | paraphrase | 0.10 | 0.889 | 0.400 | 0.900 |
| R5 | multi-hop | 1.00 | — | 0.176 | 0.000 |
| R5 | version | 0.00 | 0.900 | 0.551 | 1.000 |
| R5 | unanswerable | 1.00 | — | 0.104 | 1.000 |
| **R5** | **overall (n=50)** | **0.48** | **0.923** | **0.333** | **0.710** |

R5’s 0.05 correctness improvement is concentrated in identifier and version questions; it also answers all sampled version questions instead of abstaining on one. Neither system answered the sampled multi-hop questions correctly: both abstained on all ten. Both correctly abstained on all ten unanswerable questions. R4 has slightly higher mean faithfulness among non-abstained answers, while R5 has higher relevance and correctness overall. These judge outcomes should be read alongside the retrieval results and the small, fixed sample rather than as a claim of statistical significance.

## 5. Manual audit: 10 R5 judge decisions

“Judge verdict” below refers to the correctness score in `results/judge_r5.jsonl` (1 = correct, 0.5 = partial, 0 = wrong). The manual assessment checks the question, ground truth, generated answer, and judge explanation. Scores are shown as **abstained / faithfulness / answer relevance / correctness**; `—` means faithfulness is not scored for an abstention.

| ID | Question | Ground truth | R5 answer | Judge scores | Manual agreement and rationale |
|---|---|---|---|---|---|
| `dev004` | Which setting controls how many times the mechanism that parks messages nobody could process tries again before it gives up? | `dlq.max_retries` | “The documentation does not contain this information.” | yes / — / 0.290 / 0.0 | **Agree: wrong.** The answer abstained even though the required setting is documented. The top five retrieved documents did not contain either relevant `dlq.max_retries` document. |
| `dev008` | In PaderQueue 4.x, what does `metrics.interval_s` default to? | `10` | “10 seconds” | no / 1.000 / 0.054 / 1.0 | **Agree: correct.** It gives the exact numeric default and unit. The low relevance score does not make the factual answer wrong. |
| `dev009` | What was the default value of `compactor.compression` in PaderQueue 2.x? | `none` | “`compactor.compression` defaulted to `none` in PaderQueue 2.x.” | no / 1.000 / 0.970 / 1.0 | **Agree: correct.** The answer gives the right value and explicitly matches the requested version. |
| `dev011` | Which setting controls how long the central process that receives and forwards all messages waits for an answer before it counts the attempt as failed? | `broker.timeout_ms` | “`broker.timeout_ms` (PaderQueue 3.x).” | no / 1.000 / 0.428 / 1.0 | **Agree: correct.** The setting name is the required information; the version qualifier is consistent with the retrieved configuration. |
| `dev025` | Which permanent fix does the documentation recommend for the error that caused incident INC-2024-171? | Follow PQ-E1915: add capacity or reduce load; raise `metrics.threshold_percent` only as a last resort. | “The documentation does not contain this information.” | yes / — / 0.188 / 0.0 | **Agree: wrong.** The incident report was retrieved, but the relevant PQ-E1915 error-catalogue document was not. The answer should have followed the incident’s error-code reference or retrieved that second hop. |
| `dev030` | Which permanent fix does the documentation recommend for the error that caused incident INC-2025-175? | Check logs for the underlying cause; if failures are transient, increase `dlq.max_retries`. | “The documentation does not contain this information.” | yes / — / 0.209 / 0.0 | **Agree: wrong.** The incident report was retrieved, but its referenced PQ-E2617 catalogue entry was absent from the provided top five. |
| `dev062` | What should I do when PaderQueue logs PQ-E3177? | Check for client connection leaks; if load is legitimate, increase `scheduler.max_connections`. | “PQ-E3177 means the scheduler connection limit was reached. Check whether scheduler load is too high; the context does not specify a definitive remediation.” | no / 1.000 / 0.583 / 0.5 | **Agree: partial.** The response identifies the issue but omits both documented remediation steps and incorrectly says there is no definitive fix. The relevant error-catalogue document was not in the top five contexts. |
| `dev068` | What is the recommended fix for PQ-E4007? | Set `broker.compression` to the same value on all nodes, then restart them one after another. | “The documentation does not contain this information.” | yes / — / 0.169 / 0.0 | **Agree: wrong.** The error-catalogue entry was not retrieved in the top five, so the abstention follows a retrieval miss but is still incorrect end-to-end. |
| `dev073` | In PaderQueue 4.x, what does `coordinator.threshold_percent` default to? | `85` | “`coordinator.threshold_percent` defaults to `85`.” | no / 1.000 / 0.761 / 1.0 | **Agree: correct.** The exact setting and default are both present in the answer. |
| `dev087` | Which setting limits how many clients can talk to the part that holds back messages until a later point in time in parallel? | `scheduler.max_connections` | “`scheduler.max_connections`” | no / 0.000 / 0.442 / 1.0 | **Agree with correctness; note a support issue.** The answer matches the ground-truth setting, so correctness 1.0 is appropriate. The separate faithfulness score of 0.0 is also plausible: the retrieved contexts do not contain that setting’s supporting documentation, meaning the correct answer was not grounded in the supplied evidence. |

## 6. Failure analysis: five R5 questions with correctness below 1

R5 is the best system by aggregate retrieval metrics. For each case, “retrieved docs” lists the five documents actually passed to answer generation, and “relevant docs” gives the ground-truth document groups (each group represents one required fact; any listed ID in a group is acceptable). `context_recall@5` is from the per-question R5 retrieval metrics. In all five examples below, the primary issue is retrieval coverage: where a relevant source is absent, generation either abstains or gives an incomplete response. No sampled R5 correctness failure has full `context_recall@5 = 1.0`.

| ID | Question | Ground truth | Correctness | Context recall@5 | Retrieved top-five documents (ID: title) | Relevant documents (ID: title) | Failure type and analysis |
|---|---|---|---:|---:|---|---|---|
| `dev004` | Which setting controls how many times the mechanism that parks messages nobody could process tries again before it gives up? | `dlq.max_retries` | 0.0 | 0.0 | `d0805`: PaderQueue 2.1 release notes; `d0749`: acktracker.max_retries; `d0017`: What does spool.interval_s do?; `d0603`: acktracker.batch_size (PaderQueue 3.x); `d0604`: PaderQueue 3.1 release notes | `d0032`: dlq.max_retries **or** `d0303`: dlq.max_retries (PaderQueue 3.x) | **Retrieval failure.** Neither relevant document appears in the top five. The answer abstains instead of guessing, but the documentation does contain the answer. |
| `dev025` | Which permanent fix does the documentation recommend for the error that caused incident INC-2024-171? | For PQ-E1915: add capacity or reduce load; raise `metrics.threshold_percent` only as a last resort. | 0.0 | 0.5 | `d0253`: Postmortem INC-2024-171; `d0772`: Postmortem INC-2024-180; `d0417`: Postmortem INC-2024-124; `d0148`: Postmortem INC-2024-205; `d0152`: Postmortem INC-2025-137 | `d0253`: Postmortem INC-2024-171 **and** `d0183`: PQ-E1915 METRICS_THROTTLED | **Retrieval failure (missing second hop).** The incident report is found, but its referenced error-catalogue article is not. The answer abstains because the permanent fix is not in the supplied contexts. |
| `dev042` | What is the current default value of the setting that the error catalogue recommends changing for PQ-E2051? | `compactor.compression` defaults to `lz4` in 4.x. | 0.0 | 0.0 | `d0785`: PQ-E2051 after upgrade?; `d0644`: Postmortem INC-2024-200; `d0324`: Postmortem INC-2025-169; `d0095`: PQ-E3805 DLQ_COMPONENT_DISABLED; `d0174`: PQ-E2617 DLQ_RETRIES_EXHAUSTED | `d0738`: PQ-E2051 COMPACTOR_CODEC_MISMATCH **and** `d0564`: compactor.compression | **Retrieval failure.** Neither the official error entry nor the configuration entry needed to link the recommended setting to its current value is in the top five. |
| `dev062` | What should I do when PaderQueue logs PQ-E3177? | Check for client connection leaks; if load is legitimate, increase `scheduler.max_connections`. | 0.5 | 0.0 | `d0635`: PQ-E3177 after upgrade?; `d0873`: PaderQueue 3.2 release notes; `d0197`: Postmortem INC-2025-198; `d0496`: Postmortem INC-2025-142; `d0919`: Postmortem INC-2025-101 | `d0227`: PQ-E3177 SCHEDULER_CONNECTION_LIMIT_REACHED | **Retrieval failure.** The top-five results miss the official fix. The generated response captures the connection-limit symptom but cannot supply the documented remediation and incorrectly says no definitive remediation is provided. |
| `dev068` | What is the recommended fix for PQ-E4007? | Set `broker.compression` to the same value on all nodes, then restart them one after another. | 0.0 | 0.0 | `d0056`: Postmortem INC-2024-117; `d0391`: Postmortem INC-2025-116; `d0854`: PQ-E4007 after upgrade?; `d0590`: Postmortem INC-2024-188; `d0726`: Postmortem INC-2025-202 | `d0033`: PQ-E4007 BROKER_CODEC_MISMATCH | **Retrieval failure.** Related incidents and a forum thread rank above the authoritative error-catalogue fix, so generation abstains. |

The multi-hop examples point to an actionable weakness: retrieving an incident or error-code discussion alone is insufficient when the question asks for the referenced catalogue fix or a setting’s current value. Retrieval should preserve room for linked second-hop evidence and favor the official error/config reference over multiple near-duplicate incident reports.

## 7. Deployment recommendation

**Deploy R4: recursive 600-character chunks, local `all-MiniLM-L6-v2` dense retrieval plus identifier-aware BM25, min-max-normalized score fusion with `alpha=0.5`, and no cross-encoder reranking.**

R4 is the best measured quality/latency trade-off for an interactive deployment. It delivers **Recall@5 0.583 / Precision@5 0.561**, improving substantially on dense R3-600 (0.350 / 0.260) and BM25 R1 recall (0.533), at **0.308 ms retrieval latency/query**. R5 raises retrieval to **0.613 / 0.599** and the sampled judge correctness to **0.71 versus 0.66** for R4, but adds about **2,659 ms/query** for reranking—roughly **8,600×** R4’s retrieval latency—for a +0.029 Recall@5 gain. It also uses slightly more prompt context (about 615 versus 606 top-five tokens) and has marginally higher observed LLM spend for the 50-question sample (about **$0.01342 total for generation plus judging versus $0.01266** for R4). The generation prompt averages are about 794 tokens for R5 and 769 for R4.

R4 therefore retains the large retrieval and latency gains over the simpler baselines while avoiding R5’s seconds-scale reranking cost. The end-to-end judge sample still exposes a weakness shared by both R4 and R5—multi-hop answers were all incorrect in the sampled ten—so improving linked-document retrieval is more valuable than adding the current expensive reranking stage alone. The recommendation is based on the current dev-set runs; the judge comparison is a 50-question sample and should be interpreted with that scope in mind.

## Reproducibility notes

- Retrieval results: `results/metrics_r1_bm25.json`, `metrics_r2_fixed.json`, `metrics_r3_s300.json`, `metrics_r3_s600.json`, `metrics_r3_s1200.json`, `metrics_r4_hybrid.json`, and `metrics_r5_rerank.json`.
- End-to-end results: `results/judge_r4.jsonl`, `results/judge_r5.jsonl`, `results/answers_r4.jsonl`, and `results/answers_r5.jsonl`.
- Cost/latency and API cost logs: `results/cost_latency.json` and repository-level `logs/gen_r4.jsonl`, `logs/gen_r5.jsonl`, `logs/judge_answers_r4.jsonl`, `logs/judge_answers_r5.jsonl`.
- Dataset: 150 development questions total; retrieval scores cover the 120 answerable questions. The end-to-end judge uses a fixed stratified sample of 50, including 10 unanswerable questions.
