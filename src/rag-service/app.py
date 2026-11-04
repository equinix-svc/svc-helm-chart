"""RAG service: embeds in-process (fastembed ONNX), stores in Qdrant, reads source documents from the S3 store (SeaweedFS).

POST /retrieve {"query": str, "top_k": int}          -> chunks for the LiteLLM rag_augment guardrail
POST /ingest   {"bucket": "rag-docs", "prefix": ""}  -> chunk + embed every .txt / .md object into Qdrant

Derived from the earlier lab's rag-adapter (same chunking and Qdrant search), with Ollama and Gemini embeddings
replaced by a local model and the Portkey webhook contract dropped.
"""
import os
import uuid

import boto3
from botocore.config import Config
import httpx
from fastapi import FastAPI
from fastembed import TextEmbedding

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "knowledge-base")
MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
DIM = 384
CHUNK_CHARS = 1800

app = FastAPI()
embedder = TextEmbedding(MODEL)


def embed(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in embedder.embed(texts)]


def s3():
    return boto3.client(
        "s3", endpoint_url=os.environ["S3_ENDPOINT"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY"], aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        region_name="us-east-1", config=Config(s3={"addressing_style": "path"}),
    )


def ensure_collection(client: httpx.Client) -> None:
    if client.get(f"{QDRANT_URL}/collections/{COLLECTION}").status_code == 200:
        return
    client.put(f"{QDRANT_URL}/collections/{COLLECTION}",
               json={"vectors": {"size": DIM, "distance": "Cosine"}}).raise_for_status()


def chunks_of(text: str) -> list[str]:
    out, cur = [], ""
    for para in text.split("\n\n"):
        if cur and len(cur) + len(para) > CHUNK_CHARS:
            out.append(cur.strip())
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        out.append(cur.strip())
    return out


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/retrieve")
def retrieve(payload: dict):
    query, top_k = payload.get("query") or "", int(payload.get("top_k") or 3)
    if not query:
        return {"chunks": []}
    with httpx.Client(timeout=10) as client:
        r = client.post(f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
                        json={"vector": embed([query])[0], "limit": top_k, "with_payload": True})
        if r.status_code == 404:  # collection not created yet: nothing ingested
            return {"chunks": []}
        r.raise_for_status()
        return {"chunks": [
            {"text": p["payload"]["text"], "source": p["payload"].get("source", "?"), "score": round(float(p["score"]), 3)}
            for p in r.json().get("result", []) if p.get("payload", {}).get("text")
        ]}


@app.post("/ingest")
def ingest(payload: dict):
    bucket, prefix = payload.get("bucket", "rag-docs"), payload.get("prefix", "")
    client_s3, done = s3(), []
    with httpx.Client(timeout=60) as client:
        ensure_collection(client)
        for page in client_s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.lower().endswith((".txt", ".md")):
                    continue
                text = client_s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8", "replace")
                parts = chunks_of(text)
                if not parts:
                    continue
                points = [
                    {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{bucket}/{key}#{i}")), "vector": v,
                     "payload": {"text": t, "source": key, "chunk": i}}
                    for i, (t, v) in enumerate(zip(parts, embed(parts)))
                ]
                client.put(f"{QDRANT_URL}/collections/{COLLECTION}/points?wait=true",
                           json={"points": points}).raise_for_status()
                done.append({"source": key, "chunks": len(points)})
    return {"ingested": done}
