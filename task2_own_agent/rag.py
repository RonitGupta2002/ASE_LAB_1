
import os
import re
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from pathlib import Path


import tiktoken


from common.llm_client import LLMClient, count_tokens
from common.site_checker import check_site, member_names_from_content
from common.embed_images import embed_images



@dataclass
class Chunk:
    source_doc_id : str
    text          : str
    embeddings    : np.ndarray



_TASK_FOLDER        : Path = Path(__file__).resolve().parent
_STYLE_GUIDE_FOLDER : Path = _TASK_FOLDER / "style_guide"
_FILE_EXTENSION     : str = "md"

_DOCUMENT_ID_REGEX : re.Pattern = re.compile(r"SG-[0-9]+")

_ENCODING : tiktoken.Encoding = tiktoken.get_encoding("cl100k_base")


MAX_TOKENS = 100
OVERLAP_TOKENS = 50
CHUNK_LIMIT = MAX_TOKENS - OVERLAP_TOKENS
SEPARATORS = ["\n\n", "\n", ". ", " ", ""]



rag_chunks : list[Chunk] = []

llm_client : LLMClient = LLMClient(model=os.environ["LAB_FALLBACK_MODEL"],
                                   embedding_model=os.environ["LAB_EMBEDDING_MODEL"],
                                   log_path=_TASK_FOLDER / "logs" / f"run{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.jsonl")



def split_recursive(value: str, remaining_separators: list[str]) -> list[str]:
    if count_tokens(value) <= CHUNK_LIMIT:
        return [value]

    if not remaining_separators:
        tokens = _ENCODING.encode(value)
        return [
            _ENCODING.decode(tokens[i : i + CHUNK_LIMIT])
            for i in range(0, len(tokens), CHUNK_LIMIT)
        ]

    separator = remaining_separators[0]
    if not separator:
        tokens = _ENCODING.encode(value)
        return [
            _ENCODING.decode(tokens[i : i + CHUNK_LIMIT])
            for i in range(0, len(tokens), CHUNK_LIMIT)
        ]

    if separator not in value:
        return split_recursive(value, remaining_separators[1:])

    parts = value.split(separator)
    units = [
        part + (separator if index < len(parts) - 1 else "")
        for index, part in enumerate(parts)
    ]

    chunks: list[str] = []
    current = ""

    for unit in units:
        if count_tokens(unit) > CHUNK_LIMIT:
            subchunks = split_recursive(unit, remaining_separators[1:])
        else:
            subchunks = [unit]

        for subchunk in subchunks:
            if current and count_tokens(current + subchunk) > CHUNK_LIMIT:
                chunks.append(current)
                current = ""
            current += subchunk

    if current:
        chunks.append(current)

    return chunks


def _create_chunks_overlay(text : str) -> list[str]:
    if not text:
        return []

    base_chunks = split_recursive(text, SEPARATORS)
    chunks: list[str] = []

    for index, chunk in enumerate(base_chunks):
        prefix = ""
        if index > 0 and OVERLAP_TOKENS:
            previous_tokens = _ENCODING.encode(base_chunks[index - 1])
            prefix = _ENCODING.decode(previous_tokens[-OVERLAP_TOKENS:])

        chunks.append(prefix + chunk)

    return chunks


def create_rag() -> None:
    global rag_chunks

    for path in sorted(_STYLE_GUIDE_FOLDER.rglob(f"*.{_FILE_EXTENSION}")):
        document = path.read_text(encoding="utf-8")
        doc_id_match = _DOCUMENT_ID_REGEX.search(path.name)
        doc_id = ""
        chunk_list = []

        if doc_id_match is None:
            raise ValueError(f"No document ID (SG-<digits>) in filename: {path.name}")
        else:
            doc_id = doc_id_match.group(0)

        chunk_list = _create_chunks_overlay(document)
        chunk_embeddings = llm_client.embed(chunk_list)
        chunk_items = [
            Chunk(doc_id, chunk_string, chunk_embedding)
            for chunk_string, chunk_embedding in zip(chunk_list, chunk_embeddings)
        ]

        rag_chunks.extend(chunk_items)

    print("RAG created")


def search(query: str, k: int) -> list[Chunk]:
    result : list[Chunk] = []

    query_chunks     = _create_chunks_overlay(query)
    query_embeddings = llm_client.embed(query_chunks)

    if 0 != len(rag_chunks):
        ## Extract chunk embeddings
        chunk_embeddings = np.array([chunk.embeddings for chunk in rag_chunks])

        ## Normalize chunk and query embeddings
        query_norm  = np.linalg.norm(query_embeddings, axis=1, keepdims=True)
        chunk_norms = np.linalg.norm(chunk_embeddings, axis=1, keepdims=True)

        ## Similarities shape (amount of document chunks, amount of query chunks)
        similarities = (chunk_embeddings @ query_embeddings.T) / (np.maximum(chunk_norms, 1e-12) @ np.maximum(query_norm.T, 1e-12))

        ## Extract max score of each chunk - axis=1 => Get max value of the query embeddings
        scores         = similarities.max(axis=1)
        best_indices   = np.argsort(scores, descending=True)
        best_k_indices = best_indices[:k]

        result = [rag_chunks[i] for i in best_k_indices]

    else:
        raise RuntimeError("Call create_rag() before search()")

    return result
