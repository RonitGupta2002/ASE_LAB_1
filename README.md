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
| 4 | Tools for agents ([task4_tools/README.md](task4_tools/README.md)) | Done |

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



## Task 4 – Tools for agents

This task implements a tool-using agent for a sandboxed repository. The task description and implementation notes are documented in [`task4_tools/README.md`](task4_tools/README.md).

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
| `task3_rag/`, `task4_tools/` | |
