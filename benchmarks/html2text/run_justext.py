"""Run stock jusText (English stoplist, default parameters) on WebMainBench pages and write quality.py predictions.

    uv run --python 3.11 --with justext==3.0.2 --with lxml-html-clean \
        python run_justext.py wmb_en.jsonl.gz wmb-justext.predictions.jsonl

jusText is the extractor Nemotron-CC used (their settings may differ), and the paragraph splitting Marin's extractor
starts from. Expect empty output on many pages: stock jusText marks every paragraph of short-line pages
(forums, product pages) as boilerplate.
"""

import gzip
import json
import sys
import time

import justext


def main():
    src, out = sys.argv[1:3]
    stoplist = justext.get_stoplist('English')
    with gzip.open(src, 'rt', encoding='utf-8') as f, open(out, 'w', encoding='utf-8') as o:
        for idx, line in enumerate(f):
            d = json.loads(line)
            t0 = time.perf_counter()
            err = None
            try:
                paragraphs = justext.justext(d['html'].encode('utf-8'), stoplist, encoding='utf-8')
                pred = '\n'.join(p.text for p in paragraphs if not p.is_boilerplate)
            except Exception as e:
                pred, err = '', repr(e)[:200]
            row = {'idx': idx, 'prediction': pred, 'elapsed_ms': (time.perf_counter() - t0) * 1000}
            if err:
                row['error'] = err
            o.write(json.dumps(row, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
