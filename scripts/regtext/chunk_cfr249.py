import sys, re, json
import xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
chunks = []
for sec in root.iter():
    if sec.tag.startswith("DIV8") and sec.get("TYPE") == "SECTION":
        head = (sec.findtext("HEAD") or "").strip()
        num = sec.get("N") or ""
        paras = [re.sub(r"\s+", " ", "".join(p.itertext())).strip() for p in sec if p.tag in ("P", "FP")]
        text, buf, part = "", [], 0
        for p in paras:
            buf.append(p)
            if sum(len(x) for x in buf) > 1400:
                chunks.append({"chunk_id": f"CFR-{num}-{part}", "doc": "12 CFR 249 (Regulation WW)", "section": head, "pid": None, "page": None, "text": " ".join(buf)}); buf, part = [], part + 1
        if buf:
            chunks.append({"chunk_id": f"CFR-{num}-{part}", "doc": "12 CFR 249 (Regulation WW)", "section": head, "pid": None, "page": None, "text": " ".join(buf)})
json.dump(chunks, open(sys.argv[2], "w"))
print(len(chunks), "chunks;", sorted({c["section"][:40] for c in chunks})[:50])
