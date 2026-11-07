
import os
import re
from dataclasses import dataclass

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



_STYLE_GUIDE_FOLDER : Path = Path(__file__).resolve().parent / "style_guide"
_FILE_EXTENSION : str = "md"

_DOCUMENT_ID_REGEX : re.Pattern = re.compile(r"SG-[0-9]+")

_ENCODING : tiktoken.Encoding = tiktoken.get_encoding("cl100k_base")



rag_chunks : list[Chunk] = []

llm_client : LLMClient = LLMClient(model=os.environ["LAB_FALLBACK_MODEL"],
                                   embedding_model=os.environ["LAB_EMBEDDING_MODEL"])



def _create_chunks_overlay(text : str) -> list[str]:
    _CHUNK_SIZE : int = 50
    _CHUNK_OVERLAP : int = 10

    result : list[str] = []

    token_ids = _ENCODING.encode(text)
    step      = _CHUNK_SIZE - _CHUNK_OVERLAP
    starts    = np.arange(0, len(token_ids), step)
    result    = [_ENCODING.decode(token_ids[start : start + _CHUNK_SIZE]) for start in starts]

    return result


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
