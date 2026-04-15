import chromadb
import os
from index import CHROMA_DB_DIR
from dotenv import load_dotenv

load_dotenv()

def check_db():
    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    try:
        collection = client.get_collection("rag_lab")
        count = collection.count()
        print(f"Collection 'rag_lab' has {count} items.")
        if count > 0:
            peek = collection.peek(limit=1)
            # Peek returns embeddings if they are there
            if peek['embeddings']:
                dim = len(peek['embeddings'][0])
                print(f"Embedding dimension: {dim}")
            else:
                print("No embeddings found in peek result (try including them).")
                peek = collection.get(limit=1, include=['embeddings'])
                if peek['embeddings']:
                    dim = len(peek['embeddings'][0])
                    print(f"Embedding dimension (explicit): {dim}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_db()
