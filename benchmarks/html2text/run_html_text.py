"""Run html-text (Zyte's whole-page text extractor) on WebMainBench pages and write quality.py predictions.

    uv run --python 3.11 --with html-text --with lxml-html-clean \
        python run_html_text.py wmb_en.jsonl.gz wmb-html-text.predictions.jsonl

html-text keeps all of a page's text, with paragraph breaks at block tags: no main-content extraction. That is the
same approach as Common Crawl's WET files, so it stands in for WET quality (it is not Common Crawl's own code).
"""

import gzip
import json
import sys
import time

import html_text


def main():
    src, out = sys.argv[1:3]
    with gzip.open(src, 'rt', encoding='utf-8') as f, open(out, 'w', encoding='utf-8') as o:
        for idx, line in enumerate(f):
            d = json.loads(line)
            t0 = time.perf_counter()
            err = None
            try:
                pred = html_text.extract_text(d['html'])
            except Exception as e:
                pred, err = '', repr(e)[:200]
            row = {'idx': idx, 'prediction': pred, 'elapsed_ms': (time.perf_counter() - t0) * 1000}
            if err:
                row['error'] = err
            o.write(json.dumps(row, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
