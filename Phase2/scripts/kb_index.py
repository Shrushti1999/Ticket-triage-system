#!/usr/bin/env python3
import os, json
def chunk(t, size=400):
    b, parts = "", []
    for line in t.splitlines(True):
        if len(b)+len(line)>size: parts.append(b); b=""
        b += line
    if b: parts.append(b)
    return parts
docs=[]
os.makedirs("mock_data", exist_ok=True)
for f in os.listdir("mock_data/policies"):
    if f.endswith(".md"):
        txt=open(os.path.join("mock_data/policies", f),"r",encoding="utf-8").read()
        for i,c in enumerate(chunk(txt)):
            docs.append({"doc_id": f"{f}#chunk-{i+1}", "file": f, "text": c})
json.dump({"docs": docs}, open("mock_data/policy_index.json","w",encoding="utf-8"), indent=2)
print("Indexed", len(docs),"chunks")