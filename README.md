# Lab 1 – Agentic Software Engineering (WS 2026/27)

Paderborn University · Group submission for Lab 1.
The original lab instructions are kept in [`instructions.md`](instructions.md).

## Group details

| | |
|---|---|
| **Group** |8|
| **Members** |Ashmit Goel,	Florian Menzel, Narayan Singh Bhadauriya, Ronit Gupta, Vaibhav Deshpande|
| **Repository** | https://github.com/RonitGupta2002/ASE_LAB_1 |

## Overview

| Task | Description | Status |
|---|---|---|
| 0 | Gateway access and environment setup | Done |
| 1 | OpenCode setup and team website | Done |
| 2 | Custom JSON-action coding agent with style-guide RAG ([`task2_own_agent/`](task2_own_agent/)) | Done |
| 3 | RAG retrieval experiments and evaluation ([`task3_rag/REPORT.md`](task3_rag/REPORT.md)) | Done |
| 4 | Secure tools for agents ([task4_tools/README.md](task4_tools/README.md)) | Done |

## Prerequisites

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- An API key for the UPB AI Gateway (each member needs their own, create it at https://ai-gateway.upb.de)
- University network or VPN (the gateway is not reachable otherwise)

Never commit `.env` or any API key. Both `.env` and `.venv/` are in `.gitignore`.

## Task 0 – Environment setup and gateway check

Run everything from the repository root.
```bash
# 1. Install uv (once), then open a new terminal
curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Create the Python environment
uv sync
# 3. Add your key
cp .env.example .env        # then paste your key after UPB_AI_GATEWAY_KEY
# 4. Check that the gateway works
uv run python common/hello_gateway.py
```

## Task 1 – OpenCode and the team website

The team website is built by the OpenCode coding agent, using the gateway as an OpenAI-compatible provider.

### 1. Install OpenCode
```bash
curl -fsSL https://opencode.ai/install | bash
```
Open a new terminal, then check it:
```bash
opencode --version
```

### 2. Make the key available to OpenCode
OpenCode reads the key from an environment variable (not from `.env`):
```bash
echo 'export UPB_AI_GATEWAY_KEY="your-key"' >> ~/.zshrc
```
Open a new terminal and check with `echo $UPB_AI_GATEWAY_KEY`.

### 3. Run the agent
```bash
cd task1_opencode
mkdir -p site conversation
opencode
```
`task1_opencode/opencode.json` configures the provider (`upb`), the default model `GPT-6 Luna`, and asks for permission before every file edit and shell command. In the OpenCode UI, check that the status bar shows `GPT-6 Luna (default)` (otherwise use `/models`).

Inputs the agent works from:
- `task1_opencode/content/<firstname>.md`: one profile per member
- `task1_opencode/content/images/<firstname>.jpg`: one picture per member

### 4. Build and check the site
The agent runs these itself. You can also run them manually from `task1_opencode/`:

```bash
python embed_images.py site/index.html --images content/images
python check_site.py site/index.html --content content
```

`embed_images.py` replaces `{{image:<file>}}` placeholders with base64 data URIs.
`check_site.py` verifies the site (single file under 8 MB, no external resources, viewport tag, responsive CSS, day/night toggle, embedded images, all members present).

### 5. View the website
In the terminal from within the folder task1_opencode
```bash
open site/index.html
```
Try the day/night toggle and resize the window.

### 6. Save the session
Two sessions namely session_01.md and session_02.md are saved which have all the detailed related to the prompt as well as opencode stats. These are located in task1_opencode/conversation/



## Task 2 – Build your own (small) coding agent
### How to run the agent
```bash
uv run python task2_own_agent/agent.py --content task1_opencode/content --out task2_own_agent/site/index.html
```


### Design decisions

#### Chunking
Style-guide Markdown is split recursively using paragraph breaks, line breaks, sentence boundaries, spaces, and finally token boundaries (Structure-aware Chunking). The target chunk limit is 50 tokens (`MAX_TOKENS - OVERLAP_TOKENS`). Each chunk after the first receives up to 50 tokens from the previous chunk as context. This aims to preserve nearby guidance when a search retrieves only one chunk.

#### Embedding model
Embedding model is: `kiconnect.qwen3-embedding-8b`
Chat model is: `kiconnect.qwen3.8-27b`

#### k
The agent requests at most 5 results per style-guide search. This provides several relevant passages while limiting how much retrieved text is added to the conversation. The rag search function accepts `k` as an argument; the agent sets its value to five.

#### Prompt design
The system prompt describes the available actions and their argument schemas, requires JSON action responses, and reserves an HTML code block for `write_site`. It tells the agent to read the profiles, consult retrieved style guidance, avoid inventing personal details, and use image placeholders. After writing the site, the agent receives the checker report and is instructed to revise failures before finishing. The prompt also explains how to recover from invalid output and handle later user feedback.

#### How you handle invalid output
The agent attempts to parse each response as JSON and checks that it has the expected top-level keys. For responses containing an HTML block, it extracts the JSON action and HTML separately. Parse errors and unsupported actions are sent back to the model as observations. The generated page is also checked; the agent is not allowed to finish until the latest checker report has no failures.



## Task 3 – Retrieval-augmented generation

We compared BM25, dense retrieval, hybrid retrieval, and hybrid retrieval with cross-encoder reranking across the 932-document **PaderQueue** corpus (`task3_rag/data/corpus.jsonl`), evaluating retrieval quality at `k=5` across 150 development questions (120 answerable across `identifier`, `paraphrase`, `multi-hop`, and `version`, plus 30 `unanswerable`) and generating predictions for the 100 test questions (`task3_rag/data/questions_test.jsonl`)[cite: 3, 7, 19, 20]. Each chunk is prefixed with its document metadata header (`[type | title | version]`)[cite: 3, 14].

### Configurations & Summary Results
- **R1 (`r1_bm25`):** `BM25Okapi` with identifier-aware tokenization on 600-character recursive chunks — Overall Recall@5: **0.533**, Precision@5: **0.558** (`identifier` Recall@5: **0.900**, latency: **15.22 ms/query**)[cite: 3, 19].
- **R2 (`r2_fixed`):** Fixed-size 600-character chunks (overlap 100) + local `sentence-transformers/all-MiniLM-L6-v2` embeddings — Overall Recall@5: **0.342**, Precision@5: **0.266** (latency: **0.38 ms/query**)[cite: 3, 19].
- **R3 (`r3_s300`, `r3_s600`, `r3_s1200`):** Recursive markdown/paragraph/sentence chunking + local `all-MiniLM-L6-v2` embeddings across three chunk sizes (overlap 100)[cite: 7, 19]:
  - `300` chars (`r3_s300`): Recall@5 **0.467**, Precision@5 **0.385**, ~379 top-5 context tokens/query, **0.75 ms/query**[cite: 19].
  - `600` chars (`r3_s600`): Recall@5 **0.350**, Precision@5 **0.260**, ~618 top-5 context tokens/query, **0.34 ms/query**[cite: 19].
  - `1200` chars (`r3_s1200`): Recall@5 **0.354**, Precision@5 **0.275**, ~756 top-5 context tokens/query, **0.21 ms/query**[cite: 19].
- **R4 (`r4_hybrid`):** Equal-weight (`alpha=0.5`) min-max normalized score fusion of R1 and R3-600 — Overall Recall@5: **0.583**, Precision@5: **0.561**, retrieval latency: **0.31 ms/query**, 50-question Judge Correctness: **0.660** (Faithfulness: **0.957**)[cite: 19]. **Recommended for interactive production deployment**[cite: 19, 20].
- **R5 (`r5_rerank`):** R4 top-25 candidates re-ranked with `cross-encoder/ms-marco-MiniLM-L-6-v2` — Overall Recall@5: **0.613**, Precision@5: **0.599**, retrieval latency: **2,659.38 ms/query**, 50-question Judge Correctness: **0.710** (Faithfulness: **0.923**)[cite: 3, 19].

See [`task3_rag/README.md`](task3_rag/README.md) for the dataset specification and [`task3_rag/REPORT.md`](task3_rag/REPORT.md) for the full experimental report, 10-question manual judge audit, 5-question failure analysis, and deployment recommendation[cite: 3, 7, 19, 20].

### Steps to Run Task 3 and Reproduce All Results

Run all commands from the repository root[cite: 20]:

#### 1. Install local embedding and reranking dependencies
```bash
uv sync --extra local
```

#### 2. Set the UPB AI Gateway environment variables
```bash
export UPB_AI_GATEWAY_KEY="your-key"
export LAB_CHAT_MODEL="openai.gpt-6-luna"
export LAB_EMBEDDING_MODEL="kiconnect.qwen3-embedding-8b"
```

#### 3. Run all retrieval experiments (R1–R5), chunk-size ablations, and cost/latency logging
```bash
uv run python task3_rag/pipeline.py
```
This script indexes the corpus, caches embeddings in `task3_rag/.cache/`, evaluates Context Recall@5 and Context Precision@5 overall and per category using `evaluate.py`, and writes all outputs to `task3_rag/results/`[cite: 1, 3, 13, 19]:
- Ranked retrieval outputs: `retrieval_r1_bm25.jsonl`, `retrieval_r2_fixed.jsonl`, `retrieval_r3_s300.jsonl`, `retrieval_r3_s600.jsonl`, `retrieval_r3_s1200.jsonl`, `retrieval_r4_hybrid.jsonl`, `retrieval_r5_rerank.jsonl`[cite: 3, 19]
- Evaluation metrics: `metrics_r1_bm25.json`, `metrics_r2_fixed.json`, `metrics_r3_s300.json`, `metrics_r3_s600.json`, `metrics_r3_s1200.json`, `metrics_r4_hybrid.json`, `metrics_r5_rerank.json`[cite: 1, 3, 19]
- Indexing time, query latency, and context token counts: `cost_latency.json`[cite: 19]

To run `evaluate.py` directly on any individual retrieval file[cite: 1, 3]:
```bash
uv run python task3_rag/evaluate.py task3_rag/results/retrieval_r4_hybrid.jsonl --k 5 --json task3_rag/results/metrics_r4_hybrid.json
uv run python task3_rag/evaluate.py task3_rag/results/retrieval_r5_rerank.jsonl --k 5 --json task3_rag/results/metrics_r5_rerank.json
```

#### 4. Generate end-to-end answers on the 50-question stratified dev sample (R4 & R5)
```bash
uv run python task3_rag/generate_answers.py --config r4
uv run python task3_rag/generate_answers.py --config r5
```
- Saves generated answers and prompt contexts to `task3_rag/results/answers_r4.jsonl` and `task3_rag/results/answers_r5.jsonl`[cite: 2, 3, 19].
- Logs gateway token counts, latency, and API costs to `logs/gen_r4.jsonl` and `logs/gen_r5.jsonl`[cite: 5, 19].

#### 5. Evaluate end-to-end answers with the LLM Judge (`judge.py`)
```bash
uv run python task3_rag/judge.py task3_rag/results/answers_r4.jsonl --sample 50 --model openai.gpt-6-luna --local-embeddings --out task3_rag/results/judge_r4.jsonl
uv run python task3_rag/judge.py task3_rag/results/answers_r5.jsonl --sample 50 --model openai.gpt-6-luna --local-embeddings --out task3_rag/results/judge_r5.jsonl
```
- Saves per-question and per-category abstention rates, faithfulness, answer relevance, and correctness scores to `task3_rag/results/judge_r4.jsonl` and `task3_rag/results/judge_r5.jsonl`[cite: 2, 3, 19].
- Logs judge LLM calls and costs to `logs/judge_answers_r4.jsonl` and `logs/judge_answers_r5.jsonl`[cite: 2, 19].

#### 6. Generate final test set predictions (`task3_rag/predictions_test.jsonl`)
```bash
uv run python task3_rag/generate_answers.py --config r5 --test
```
- Generates answers and top-5 deduplicated `retrieved_doc_ids` for all 100 test questions in `task3_rag/data/questions_test.jsonl` and writes `task3_rag/predictions_test.jsonl`[cite: 3, 7, 17].

## Task 4 – Tools for agents

This task implements a tool-using agent for a sandboxed TinyLedger repository. The tool layer validates arguments and confines reads, writes, and subprocesses to the allowed workspace; the agent uses it to fix the issue without modifying tests. See [`task4_tools/README.md`](task4_tools/README.md) for the specification and workflow, and [`task4_tools/Threats.md`](task4_tools/Threats.md) for the threat-to-control summary.

### 1. Reset the workspace

```bash
uv run python task4_tools/reset_workspace.py
```

### 2. Run the public tests
```bash
uv run pytest task4_tools/tests -v
```

### 3. Run the mock-agent validation
```bash
uv run python task4_tools/agent.py --mock
```

### 4. Run the real agent loop
```bash
uv run python task4_tools/reset_workspace.py
uv run python task4_tools/agent.py
```

### 5. Capture the workspace diff
```bash
git -C task4_tools/workspace diff > task4_tools/final.diff
```


## Known limitations
- Search uses a fixed top-5 result count in the agent. Previous short tests showed that returned top-5 chunk often contains the interesting documents. When the documents would change then this could be a performance problem for the agent.
- Chunk sizes of ~50-100 tokens are set based on some brief tests and checks of the token length. No analysis was conducted on if an adaptive chunking length could perform better
- Chunk size is also very approximate: Can vary from 15 to 97 tokens (based on the current style guide) => Another reason for the selection of k
- The style-guide index is rebuilt on every run. There is no persistent store for the embeddings. => But not needed by the task


## Repository structure
| Path | Content |
|---|---|
| `instructions.md` | Original lab instructions |
| `common/` | Gateway client, site checker, image embedding helper |
| `task1_opencode/` | OpenCode config, member content, generated website, session exports |
| `task2_own_agent/`| Generated website, successful run log, screenshot of a successful run, overview diagram |
| `task3_rag/` | PaderQueue dataset, RAG pipeline (`pipeline.py`, `generate_answers.py`), evaluation scripts (`evaluate.py`, `judge.py`), results (`results/`), experimental report (`REPORT.md`), and test predictions (`predictions_test.jsonl`) |
| `task4_tools/` | Sandboxed TinyLedger agent, tool implementation, tests, run logs, and threat summary |
