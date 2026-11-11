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

## Repository structure
| Path | Content |
|---|---|
| `instructions.md` | Original lab instructions |
| `common/` | Gateway client, site checker, image embedding helper |
| `task1_opencode/` | OpenCode config, member content, generated website, session exports |
| `task2_own_agent/`, `task3_rag/`, `task4_tools/` | |
