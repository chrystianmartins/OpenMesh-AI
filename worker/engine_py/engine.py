#!/usr/bin/env python3
import argparse
import json
import sys
from typing import Any

from sentence_transformers import SentenceTransformer, util

MODEL_NAME = "all-MiniLM-L6-v2"


def build_error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def to_json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def handle_embed(model: SentenceTransformer, req: dict[str, Any]) -> dict[str, Any]:
    input_data = req.get("input", {})
    text = input_data.get("text")
    if not isinstance(text, str) or not text.strip():
        return build_error("EMBED requires input.text as non-empty string")

    embedding = model.encode(text, convert_to_numpy=True, normalize_embeddings=False)
    return {
        "ok": True,
        "result": {"embedding": embedding.astype(float).tolist()},
    }


def handle_rank(model: SentenceTransformer, req: dict[str, Any]) -> dict[str, Any]:
    input_data = req.get("input", {})
    query = input_data.get("query")
    texts = input_data.get("texts")

    if not isinstance(query, str) or not query.strip():
        return build_error("RANK requires input.query as non-empty string")
    if not isinstance(texts, list) or not texts or not all(isinstance(t, str) for t in texts):
        return build_error("RANK requires input.texts as non-empty string[]")

    query_emb = model.encode(query, convert_to_tensor=True, normalize_embeddings=True)
    text_emb = model.encode(texts, convert_to_tensor=True, normalize_embeddings=True)

    similarities = util.cos_sim(query_emb, text_emb)[0]
    ranked = similarities.argsort(descending=True).tolist()

    return {
        "ok": True,
        "result": {"indices": ranked},
    }


def process_request(model: SentenceTransformer, raw: str) -> dict[str, Any]:
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as exc:
        return build_error(f"invalid json: {exc}")

    action = req.get("action")
    if action == "EMBED":
        resp = handle_embed(model, req)
    elif action == "RANK":
        resp = handle_rank(model, req)
    else:
        resp = build_error("unsupported action, expected EMBED or RANK")

    resp["model_name"] = MODEL_NAME
    resp["device"] = str(model.device)
    if "id" in req:
        resp["id"] = req["id"]
    return resp


def run_server(model: SentenceTransformer) -> int:
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue

        response = process_request(model, raw)
        sys.stdout.write(to_json_line(response) + "\n")
        sys.stdout.flush()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenMesh embedding/ranking python engine")
    parser.add_argument("--server", action="store_true", help="keep processing line-delimited JSON from stdin")
    args = parser.parse_args()

    model = SentenceTransformer(MODEL_NAME)

    if args.server:
        return run_server(model)

    raw = sys.stdin.read().strip()
    if not raw:
        sys.stdout.write(to_json_line(build_error("stdin json payload is required")) + "\n")
        return 1

    response = process_request(model, raw)
    sys.stdout.write(to_json_line(response) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
