import ast
import json
import math
import operator
import os
import re
import time
import urllib.parse
import urllib.request
from devflight import Trace

HINTS = {
    "es": ["¿Qué datos conoces y qué te pide el problema?", "¿Puedes representar las cantidades con un dibujo?", "¿Puedes expresar todas las fracciones con el mismo denominador?", "¿Qué operación relaciona los datos que ya conoces?"],
    "ca": ["Quines dades coneixes i què et demana el problema?", "Pots representar les quantitats amb un dibuix?", "Pots expressar les fraccions amb el mateix denominador?", "Quina operació relaciona les dades que ja coneixes?"],
    "en": ["What do you know, and what does the problem ask?", "Can you draw the quantities?", "Can you give the fractions a common denominator?", "Which operation connects the information you have?"]}

def local_post(url, payload, timeout=55):
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.scheme != "http":
        raise ValueError("Offline copilot accepts only loopback HTTP model endpoints")
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    # Never consult proxies: model calls remain on the board.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout) as response:
        return json.load(response)

def helmcode_post(url, payload, api_key=None, timeout=55):
    api_key = api_key or os.getenv("HELMCODE_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Configure HELMCODE_API_KEY to use Helmcode inference")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)

class Index:
    def __init__(self, records=(), embedding_url=None, vectors=None):
        self.records = list(records)
        self.embedding_url = embedding_url
        self.vectors = vectors if vectors is not None else (self.embed([r["text"] for r in self.records]) if embedding_url and self.records else [])
        if self.vectors and (not embedding_url or len(self.vectors) != len(self.records)):
            raise ValueError("Embedding index requires a local endpoint and one vector per record")

    @classmethod
    def load(cls, path, embedding_url=None):
        from pathlib import Path
        text = Path(path).read_text(encoding="utf-8")
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict) and "records" in data:
            return cls(data["records"], embedding_url or data.get("embedding_url"), data.get("vectors"))
        return cls([json.loads(line) for line in text.splitlines() if line.strip()], embedding_url)

    def embed(self, texts):
        embed_url = self.embedding_url or os.getenv("HELMCODE_EMBEDDING_URL") or os.getenv("EMBEDDING_URL")
        helmcode_key = os.getenv("HELMCODE_API_KEY") or os.getenv("OPENAI_API_KEY")
        if embed_url and ("helmcode.com" in embed_url or (helmcode_key and "127.0.0.1" not in embed_url and "localhost" not in embed_url)):
            model = os.getenv("HELMCODE_EMBEDDING_MODEL", "qwen3-embedding")
            data = helmcode_post(embed_url, {"model": model, "input": texts}, api_key=helmcode_key)["data"]
            return [r["embedding"] for r in sorted(data, key=lambda r: r.get("index", 0))]
        data = local_post(self.embedding_url, {"input": texts})["data"]
        return [r["embedding"] for r in sorted(data, key=lambda r:r["index"])]

    def search(self, problem, k=1, exclude_id=None):
        query = self.embed([problem["text"]])[0] if self.vectors else None
        words = set(re.findall(r"\w+", problem["text"].lower()))
        scored = []
        for i,r in enumerate(self.records):
            if r.get("id") in (problem.get("id"), exclude_id) or r["text"] == problem["text"]:
                continue
            if query:
                vector = self.vectors[i]
                if len(query) != len(vector):
                    raise ValueError("Embedding model dimensions changed; rebuild index")
                score = sum(a*b for a,b in zip(query,vector))/(math.sqrt(sum(a*a for a in query)*sum(b*b for b in vector)) or 1)
            else:
                other = set(re.findall(r"\w+", r["text"].lower()))
                score = len(words & other)/(len(words | other) or 1)
            scored.append((score,r))
        return sorted(scored, key=lambda x: (-x[0], str(x[1].get("id"))))[:k]

def arithmetic_demo(problem):
    """Restricted AST arithmetic for transparent fixtures; never claimed as Qwen."""
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
    def calculate(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int,float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            return operations[type(node.op)](calculate(node.left), calculate(node.right))
        raise ValueError("Demo backend supports arithmetic expressions only")
    value = calculate(ast.parse(problem["text"].strip().rstrip("?"), mode="eval").body)
    for letter, option in problem.get("options", {}).items():
        if letter in "ABCDE" and math.isclose(value, float(option)):
            return letter
    raise ValueError("No matching option")

def solve(problem, index=None, k=0, exclude_id=None, image_b64=None, llm_url=None, time_limit=60, mode="challenge", backend="llama", trace=None, step=""):
    trace = trace or Trace(agent="math-copilot", kind="teaching_eval" if mode == "study" else "m3kang_eval")
    start = time.perf_counter()
    if mode not in ("study", "challenge"):
        raise ValueError("Unknown mode")
    recipe = json.loads(os.getenv("DEVFLIGHT_RECIPE", "{}"))
    k = min(int(recipe.get("rag_k", k)), 2)
    trace.emit("skill.invoked", {"name": "minimal-hint" if mode == "study" else "answer-letter", "recipe": recipe})
    examples = index.search(problem, k, exclude_id) if index and k else []
    trace.emit("rag.retrieved", {"query": problem["text"], "examples": examples, "strategy": "embeddings" if index and index.vectors else "lexical"})
    language = problem.get("language", "en").lower()[:2]
    hints = HINTS.get(language, HINTS["en"])
    if mode == "study":
        # The model selects a vetted hint; free-form model output is never shown to a learner.
        messages = [{"role":"system", "content":"Choose a hint index 0-3. Never solve. Hints: " + json.dumps(hints)},
                    {"role":"user", "content":problem["text"] + "\nStudent step: " + step}]
    else:
        messages = [{"role":"system", "content":recipe.get("prompt", "Solve the math problem. Return only A, B, C, D or E.")}]
        for _,example in examples:
            messages.extend([{"role":"user", "content":example["text"][:400]}, {"role":"assistant", "content":example.get("label", "")}])
        messages.append({"role":"user", "content":problem["text"] + "\n" + json.dumps(problem.get("options", {}))})
    trace.emit("llm.request", {"messages": messages, "backend": backend})
    result = {"answer": "", "status": "ok", "prompt_tokens": 0, "examples": examples, "backend": backend}
    try:
        if backend == "demo":
            raw = "2" if mode == "study" and "/" in problem["text"] else "0" if mode == "study" else arithmetic_demo(problem)
        elif backend == "llama":
            url = llm_url or os.getenv("LLAMA_URL", "http://127.0.0.1:8080/v1/chat/completions")
            if image_b64:
                raise ValueError("Vision is not provisioned; supply a text problem")
            response = local_post(url, {"messages":messages, "temperature":0, "seed":42, "max_tokens":1,
                "grammar":"root ::= [0-3]" if mode == "study" else "root ::= [A-E]", "cache_prompt":True}, max(.1, time_limit-(time.perf_counter()-start)-1))
            trace.emit("llm.response", response)
            raw = response["choices"][0]["message"]["content"].strip()
            result["prompt_tokens"] = response.get("usage", {}).get("prompt_tokens", 0)
            result["model"] = response.get("model", "provisioned-local-model")
        elif backend == "helmcode":
            base_url = os.getenv("HELMCODE_BASE_URL", "https://api.helmcode.com/v1").rstrip("/")
            url = llm_url or os.getenv("HELMCODE_CHAT_URL", f"{base_url}/chat/completions")
            model = os.getenv("HELMCODE_MODEL", "qwen3.6")
            api_key = os.getenv("HELMCODE_API_KEY") or os.getenv("OPENAI_API_KEY")
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0,
                "max_tokens": 300
            }
            response = helmcode_post(url, payload, api_key=api_key, timeout=max(.1, time_limit - (time.perf_counter() - start) - 1))
            trace.emit("llm.response", response)
            content = (response["choices"][0]["message"].get("content") or "").strip()
            if mode == "study":
                match = re.search(r"\b([0-3])\b", content)
                raw = match.group(1) if match else ("0" if not content else content[0])
            else:
                match = re.search(r"\b([A-E])\b", content)
                raw = match.group(1) if match else (content[0] if content and content[0] in "ABCDE" else "")
            result["prompt_tokens"] = response.get("usage", {}).get("prompt_tokens", 0)
            result["model"] = response.get("model", model)
        else:
            raise ValueError("Unknown backend")
        if backend == "demo":
            trace.emit("llm.response", {"content":raw, "backend":"demo-arithmetic"})
        if mode == "study":
            result["hint"] = hints[int(raw)] if raw in "0123" and len(raw) == 1 else hints[0]
        elif re.fullmatch("[A-E]", raw):
            result["answer"] = raw
        else:
            raise ValueError("Model did not return one letter")
    except Exception as error:
        result["status"] = "error"
        result["error"] = str(error)
        if mode == "study":
            result["hint"] = hints[0]
        trace.emit("error", {"message":str(error)}, "error")
    result["seconds"] = time.perf_counter()-start
    trace.emit("board.event", {"mode":mode, "result":result})
    return result
