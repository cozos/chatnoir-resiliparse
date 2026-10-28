"""Compare extractors page by page on WebMainBench, with and without Markdown symbols.

    uv run --python 3.11 --with jieba python compare.py wmb_en.jsonl.gz \
        marin=wmb-marin-rust.predictions.jsonl magic-text=wmb-magic-text.predictions.jsonl [--perpage perpage.json]

For each page and extractor: ROUGE-5 precision, recall and F1 against the reference, tokenized and counted exactly
like quality.py, and again "content-only", after dropping tokens made only of Markdown punctuation and whitespace
(# | * - and so on) from both the reference and the prediction. A gap that survives content-only is about which text
was kept, not how it was formatted. Prints means overall and by difficulty level; --perpage writes every page's
scores as JSON ({"name|false": {idx: [p, r, f1]}, "name|true": ...}) for further digging.
"""

import argparse
import collections
import gzip
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quality import load_predictions, rouge_n  # noqa: E402

MARKDOWN = re.compile(r'^[\s#|*_\-=>`~:+\[\]()!\\]*$')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('dataset')
    parser.add_argument('predictions', nargs='+', metavar='NAME=PREDICTIONS')
    parser.add_argument('-n', type=int, default=5)
    parser.add_argument('--by', default='snapshot')
    parser.add_argument('--perpage', help='write per-page scores to this JSON file')
    args = parser.parse_args()

    import jieba
    jieba.setLogLevel(60)

    with gzip.open(args.dataset, 'rt', encoding='utf-8') as f:
        docs = [json.loads(line) for line in f if line.strip()]
    preds = {}
    for spec in args.predictions:
        name, _, path = spec.partition('=')
        preds[name] = load_predictions(path)

    def tokens(text, content_only):
        t = jieba.lcut(text or '')
        return [x for x in t if not MARKDOWN.match(x)] if content_only else t

    scores = collections.defaultdict(dict)
    for i, d in enumerate(docs):
        for content_only in (False, True):
            ref = tokens(d.get('final_output'), content_only)
            for name, rows in preds.items():
                pred = tokens(rows[i].get('prediction'), content_only)
                scores[(name, content_only)][i] = (1.0, 1.0, 1.0) if not ref and not pred else rouge_n(ref, pred, args.n)

    for content_only in (False, True):
        print('\ncontent-only (Markdown symbols dropped)' if content_only else 'as scored (quality.py tokens)')
        for name in preds:
            s = scores[(name, content_only)]
            groups = collections.defaultdict(list)
            for i, x in s.items():
                groups[str(docs[i].get(args.by))].append(x[2])
            p, r, f1 = (statistics.fmean(x[k] for x in s.values()) for k in range(3))
            print(f'  {name:16s} P {p:.3f} R {r:.3f} F1 {f1:.3f}  ' +
                  ' '.join(f'{k} {statistics.fmean(v):.3f}' for k, v in sorted(groups.items())))

    if args.perpage:
        with open(args.perpage, 'w') as f:
            json.dump({f'{n}|{str(c).lower()}': v for (n, c), v in scores.items()}, f)


if __name__ == '__main__':
    main()
