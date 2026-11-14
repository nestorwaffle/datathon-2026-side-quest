"""Build a reusable local retrieval index from organizer-compatible JSONL."""
import argparse
import json
from pathlib import Path
from copilot.pipeline import Index

def main():
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--output",required=True)
    p.add_argument("--embedding-url",help="Local llama.cpp bge embedding server; omit for lexical retrieval")
    args=p.parse_args()
    records=[json.loads(line) for line in Path(args.input).read_text(encoding="utf-8").splitlines() if line.strip()]
    index=Index(records,args.embedding_url)
    Path(args.output).write_text(json.dumps({"version":1,"embedding_url":args.embedding_url,"records":records,"vectors":index.vectors},ensure_ascii=False),encoding="utf-8")
    print(json.dumps({"records":len(records),"strategy":"embeddings" if index.vectors else "lexical"}))

if __name__=="__main__":main()
