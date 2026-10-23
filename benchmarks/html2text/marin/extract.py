"""Run one extraction variant over the HTML records written by bench.py dump; save its outputs (jsonl) and CPU time.

    <venv>/bin/python extract.py VARIANT RECORDS OUT.jsonl
VARIANT: plain (extract_plain_text, main_content=True), all_text (main_content=False),
         marin_full (Marin's production convert_page(): extract_simplified_dom + markdownify)
"""
import json, os, struct, sys, time
from resiliparse.parse.encoding import bytes_to_str, detect_encoding
from resiliparse.parse.html import HTMLTree
from resiliparse.extract.html2text import extract_plain_text

variant, records_path, out_path = sys.argv[1:4]
docs = []
with open(records_path, 'rb') as f:
    while hdr := f.read(8):
        lu, lh = struct.unpack('<II', hdr); f.seek(lu, 1); h = f.read(lh)
        if h.strip(): docs.append(h)

if variant == 'marin_full':
    sys.path.insert(0, os.environ['MARIN_SHIM'])  # see marin_shim.sh
    from marin_web_convert import convert_page
    run = lambda h: convert_page(bytes_to_str(h, detect_encoding(h)))['content']
else:
    mc = variant == 'plain'
    run = lambda h: extract_plain_text(HTMLTree.parse_from_bytes(h, detect_encoding(h)), main_content=mc)

outs = []
t0 = time.process_time()
for h in docs:
    outs.append(run(h))
cpu = time.process_time() - t0
with open(out_path, 'w') as f:
    for o in outs: f.write(json.dumps(o) + '\n')
import importlib.metadata as md
print(json.dumps(dict(out=os.path.basename(out_path), variant=variant, version=md.version('resiliparse'),
                 pages=len(docs), cpu=cpu)))
