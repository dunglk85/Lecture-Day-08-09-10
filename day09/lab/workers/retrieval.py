"""
workers/retrieval.py — Retrieval Worker
Sprint 2: Implement retrieval từ ChromaDB, trả về chunks + sources.

Input (từ AgentState):
    - task: câu hỏi cần retrieve
    - (optional) retrieved_chunks nếu đã có từ trước

Output (vào AgentState):
    - retrieved_chunks: list of {"text", "source", "score", "metadata"}
    - retrieved_sources: list of source filenames
    - worker_io_log: log input/output của worker này

Gọi độc lập để test:
    python workers/retrieval.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Add parent directory to sys.path to allow importing from index.py
sys.path.append(str(Path(__file__).parent.parent))

try:
    from index import CHROMA_DB_DIR
except ImportError:
    # Fallback if import fails
    CHROMA_DB_DIR = str(Path(__file__).parent.parent / "chroma_db")

# ─────────────────────────────────────────────
# Worker Contract (xem contracts/worker_contracts.yaml)
# Input:  {"task": str, "top_k": int = 3}
# Output: {"retrieved_chunks": list, "retrieved_sources": list, "error": dict | None}
# ─────────────────────────────────────────────

WORKER_NAME = "retrieval_worker"
DEFAULT_TOP_K = 3

def _get_embedding_fn():
    """
    Trả về embedding function.
    Ưu tiên OpenAI nếu có API key, nếu không dùng Sentence Transformers (nếu cài), 
    cuối cùng là random (chỉ để test cấu trúc).
    """
    
    # 1. Thử OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            def embed(text: str) -> list:
                if not text.strip(): return [0.0] * 1536
                resp = client.embeddings.create(input=text, model="text-embedding-3-small")
                return resp.data[0].embedding
            return embed
        except ImportError:
            print("⚠️  OpenAI library not found. Falling back...")
        except Exception as e:
            print(f"⚠️  OpenAI client error: {e}")

    # 2. Thử Sentence Transformers (offline)
    try:
        from sentence_transformers import SentenceTransformer
        # model = SentenceTransformer("all-MiniLM-L6-v2") # 384 dim
        # Lưu ý: Nếu index dùng OpenAI (1536 dim) mà retrieval dùng ST (384 dim), sẽ lỗi.
        # Chúng ta giả định dùng cùng loại đã build ở index.py
        model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2") # match some patterns
        def embed_st(text: str) -> list:
            return model.encode(text).tolist()
        return embed_st
    except ImportError:
        pass

    # 3. Fallback: random embeddings (Coi chừng dimension mismatch)
    import random
    # Match OpenAI text-embedding-3-small dimension (1536)
    def embed_random(text: str) -> list:
        return [random.random() for _ in range(1536)]
    print("⚠️  CRITICAL WARNING: Using RANDOM embeddings. Retrieval will NOT yield meaningful results.")
    return embed_random


def _get_collection():
    """
    Kết nối ChromaDB collection.
    """
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    try:
        collection = client.get_collection("rag_lab")
    except Exception:
        # Auto-create nếu chưa có
        collection = client.get_or_create_collection(
            "rag_lab",
            metadata={"hnsw:space": "cosine"}
        )
        print(f"⚠️  Collection 'rag_lab' chưa có data. Chạy index script trước.")
    return collection


def retrieve_dense(query: str, top_k: int = DEFAULT_TOP_K) -> list:
    """
    Dense retrieval: embed query → query ChromaDB → trả về top_k chunks.
    """
    if not query.strip():
        return []

    try:
        embed_fn = _get_embedding_fn()
        query_embedding = embed_fn(query)

        collection = _get_collection()
        item_count = collection.count()
        if item_count == 0:
            print(f"⚠️  Collection is empty!")
            return []

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "distances", "metadatas"]
        )

        chunks = []
        if results and results.get("documents") and len(results["documents"][0]) > 0:
            for i in range(len(results["documents"][0])):
                doc = results["documents"][0][i]
                dist = results["distances"][0][i]
                meta = results["metadatas"][0][i]
                
                chunks.append({
                    "text": doc,
                    "source": meta.get("source", "unknown"),
                    "score": round(1 - dist, 4),  # cosine similarity
                    "metadata": meta,
                })
        else:
            print(f"ℹ️  No results found for query: {query[:50]}...")
            
        return chunks

    except Exception as e:
        print(f"❌ ChromaDB query failed: {e}")
        return []


def run(state: dict) -> dict:
    """
    Worker entry point.
    """
    task = state.get("task", "")
    top_k = state.get("retrieval_top_k", DEFAULT_TOP_K)

    state.setdefault("workers_called", [])
    state.setdefault("history", [])

    state["workers_called"].append(WORKER_NAME)

    worker_io = {
        "worker": WORKER_NAME,
        "input": {"task": task, "top_k": top_k},
        "output": None,
        "error": None,
    }

    try:
        chunks = retrieve_dense(task, top_k=top_k)
        sources = list({c["source"] for c in chunks})

        state["retrieved_chunks"] = chunks
        state["retrieved_sources"] = sources

        worker_io["output"] = {
            "chunks_count": len(chunks),
            "sources": sources,
        }
        state["history"].append(
            f"[{WORKER_NAME}] retrieved {len(chunks)} chunks from {sources}"
        )

    except Exception as e:
        worker_io["error"] = {"code": "RETRIEVAL_FAILED", "reason": str(e)}
        state["retrieved_chunks"] = []
        state["retrieved_sources"] = []
        state["history"].append(f"[{WORKER_NAME}] ERROR: {e}")

    state.setdefault("worker_io_logs", []).append(worker_io)
    return state


if __name__ == "__main__":
    print("=" * 50)
    print("Retrieval Worker — Standalone Test")
    print("=" * 50)

    test_queries = [
        "SLA ticket P1 là bao lâu?",
        "Điều kiện được hoàn tiền là gì?",
        "Ai phê duyệt cấp quyền Level 3?",
    ]

    for query in test_queries:
        print(f"\n▶ Query: {query}")
        result = run({"task": query})
        chunks = result.get("retrieved_chunks", [])
        print(f"  Retrieved: {len(chunks)} chunks")
        for c in chunks[:2]:
            print(f"    [{c['score']:.3f}] {c['source']}: {c['text'][:80]}...")
        print(f"  Sources: {result.get('retrieved_sources', [])}")

    print("\n✅ retrieval_worker test done.")
