# Task 2 – Build your own (small) coding agent
## How to run the agent
```bash
uv run python task2_own_agent/agent.py --content task1_opencode/content --out task2_own_agent/site/index.html
```


## Design decisions

### Chunking
Style-guide Markdown is split recursively using paragraph breaks, line breaks, sentence boundaries, spaces, and finally token boundaries (Structure-aware Chunking). The target chunk limit is 50 tokens (`MAX_TOKENS - OVERLAP_TOKENS`). Each chunk after the first receives up to 50 tokens from the previous chunk as context. This aims to preserve nearby guidance when a search retrieves only one chunk.

### Embedding model
Embedding model is: `kiconnect.qwen3-embedding-8b`
Chat model is: `kiconnect.qwen3.8-27b`

### k
The agent requests at most 5 results per style-guide search. This provides several relevant passages while limiting how much retrieved text is added to the conversation. The rag search function accepts `k` as an argument; the agent sets its value to five.

### Prompt design
The system prompt describes the available actions and their argument schemas, requires JSON action responses, and reserves an HTML code block for `write_site`. It tells the agent to read the profiles, consult retrieved style guidance, avoid inventing personal details, and use image placeholders. After writing the site, the agent receives the checker report and is instructed to revise failures before finishing. The prompt also explains how to recover from invalid output and handle later user feedback.

### How you handle invalid output
The agent attempts to parse each response as JSON and checks that it has the expected top-level keys. For responses containing an HTML block, it extracts the JSON action and HTML separately. Parse errors and unsupported actions are sent back to the model as observations. The generated page is also checked; the agent is not allowed to finish until the latest checker report has no failures.


## Known limitations
- Search uses a fixed top-5 result count in the agent. Previous short tests showed that returned top-5 chunk often contains the interesting documents. When the documents would change then this could be a performance problem for the agent.
- Chunk sizes of ~50-100 tokens are set based on some brief tests and checks of the token length. No analysis was conducted on if an adaptive chunking length could perform better
- Chunk size is also very approximate: Can vary from 15 to 97 tokens (based on the current style guide) => Another reason for the selection of k
- The style-guide index is rebuilt on every run. There is no persistent store for the embeddings. => But not needed by the task
