import sys, re, json
from pypdf import PdfReader
pages = [(i + 1, (p.extract_text() or "")) for i, p in enumerate(PdfReader(sys.argv[1]).pages)]
print("pages", len(pages), "chars", sum(len(t) for _, t in pages))
chunks = []
# 1. product (PID) definitions: "O.D.8: Affiliated Sweep Accounts" ... up to the next PID heading
full = ""; offsets = []
for pg, t in pages:
    offsets.append((len(full), pg)); full += t.replace("’", "'") + "\n"
pat = re.compile(r"(?m)^\s*((?:I|O|S)\.[A-Z]{1,2}\.\d{1,2})\s*[:\-–]\s*([^\n]{3,90})")
hits = [m for m in pat.finditer(full)]
page_of = lambda pos: max(pg for off, pg in offsets if off <= pos)
seen = {}
for i, m in enumerate(hits):
    end = hits[i + 1].start() if i + 1 < len(hits) else min(len(full), m.start() + 3000)
    txt = re.sub(r"\s+", " ", full[m.start():min(end, m.start() + 3000)]).strip()
    pid = m.group(1)
    if "...." in m.group(2):          # a table-of-contents line, not the definition
        continue
    if len(txt) < 80 or pid in seen and len(seen[pid]) >= len(txt):
        continue
    seen[pid] = txt
    chunks.append({"chunk_id": f"INS-{pid}", "doc": "FR 2052a Instructions", "section": f"{pid} {m.group(2).strip()}", "pid": pid, "page": page_of(m.start()), "text": txt})
# 2. every page in ~1,500-character passages (fields, tables, appendices)
for pg, t in pages:
    t = re.sub(r"\s+", " ", t).strip()
    for j in range(0, len(t), 1400):
        part = t[j:j + 1600]
        if len(part) > 200:
            chunks.append({"chunk_id": f"INS-p{pg}-{j // 1400}", "doc": "FR 2052a Instructions", "section": f"page {pg}", "pid": None, "page": pg, "text": part})
json.dump(chunks, open(sys.argv[2], "w"))
print("pid definitions", len(seen), "total chunks", len(chunks)); print(list(seen)[:12]); print(seen.get("O.D.8", "")[:400])
