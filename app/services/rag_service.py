from __future__ import annotations
from pathlib import Path
from typing import List

BASE_DIR = Path(__file__).resolve().parents[2]
KB_DIR = BASE_DIR / "app" / "knowledge_base"
CHROMA_DIR = BASE_DIR / "data" / "chroma"


class RAGService:
    def __init__(self):
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        KB_DIR.mkdir(parents=True, exist_ok=True)
        # ChromaDB disabled due to initialization errors
        self.client = None
        self.collection = None
        self.chroma_enabled = False

    def ingest_knowledge_files(self):
        docs = []
        ids = []
        metadatas = []
        for index, file_path in enumerate(KB_DIR.glob("*.txt")):
            text = file_path.read_text(encoding="utf-8")
            chunks = [text[i:i+800] for i in range(0, len(text), 800)]
            for chunk_idx, chunk in enumerate(chunks):
                ids.append(f"{file_path.stem}-{chunk_idx}")
                docs.append(chunk)
                metadatas.append({"source": file_path.name})
        if docs:
            existing = set(self.collection.get().get("ids", []))
            add_ids, add_docs, add_metas = [], [], []
            for i, d, m in zip(ids, docs, metadatas):
                if i not in existing:
                    add_ids.append(i)
                    add_docs.append(d)
                    add_metas.append(m)
            if add_docs:
                self.collection.add(ids=add_ids, documents=add_docs, metadatas=add_metas)

    def search(self, query: str, n_results: int = 3) -> List[dict]:
        self.ingest_knowledge_files()
        if self.collection.count() == 0:
            return []
        res = self.collection.query(query_texts=[query], n_results=n_results)
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        return [{"text": d, "source": m.get("source", "knowledge_base")} for d, m in zip(docs, metas)]


rag_service = RAGService()
