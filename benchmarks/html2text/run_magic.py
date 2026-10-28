"""Run magic-html on WebMainBench pages and write quality.py predictions, as plain text and as Markdown.

    uv run --python 3.12 --with magic-html --with html-text --with lxml-html-clean --with markdownify \
        python run_magic.py wmb_en.jsonl.gz wmb-magic-text.predictions.jsonl wmb-magic-md.predictions.jsonl

magic-html (opendatalab, needs Python 3.12+) returns the main-content HTML; the default GeneralExtractor is used with
each page's URL. That HTML is converted to plain text with html-text and to Markdown with markdownify, and both are
written. elapsed_ms is magic-html's extraction alone, not the conversion.
"""

import gzip
import json
import sys
import time
import warnings

import html_text
from magic_html import GeneralExtractor
from markdownify import markdownify


def main():
    src, out_txt, out_md = sys.argv[1:4]
    warnings.filterwarnings('ignore')   # magic-html's regexes raise SyntaxWarnings on import and use
    extractor = GeneralExtractor()
    with gzip.open(src, 'rt', encoding='utf-8') as f, open(out_txt, 'w', encoding='utf-8') as ot, \
            open(out_md, 'w', encoding='utf-8') as om:
        for idx, line in enumerate(f):
            d = json.loads(line)
            t0 = time.perf_counter()
            err = None
            main_html = ''
            try:
                main_html = extractor.extract(d['html'], base_url=d.get('url', '')).get('html') or ''
            except Exception as e:
                err = repr(e)[:200]
            ms = (time.perf_counter() - t0) * 1000
            text = md = ''
            if main_html:
                try:
                    text = html_text.extract_text(main_html)
                    md = markdownify(main_html, heading_style='ATX')
                except Exception as e:
                    err = err or repr(e)[:200]
            for o, pred in ((ot, text), (om, md)):
                row = {'idx': idx, 'prediction': pred, 'elapsed_ms': ms}
                if err:
                    row['error'] = err
                o.write(json.dumps(row, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
