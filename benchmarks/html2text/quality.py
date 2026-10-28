"""
Score extraction outputs against a labeled dataset: ROUGE-N precision, recall and F1 of each prediction against the
dataset's reference text, plus empty outputs, errors and time per document.

    python quality.py DATASET.jsonl.gz NAME=PREDICTIONS.jsonl [NAME=PREDICTIONS.jsonl ...]

DATASET has one JSON object per line with "html" and the reference in "final_output" (the format wmb_convert.py in
benchmark-extract/ writes for WebMainBench). PREDICTIONS has rows {"idx", "prediction", "elapsed_ms"} as written by
rp-bench or ``bench.py predict``.

Tokens come from jieba, and n-grams are counted the way rouge_score does, which is how Marin scored WebMainBench
(benchmark-extract/wmb_rouge5.py), so ROUGE-5 numbers are comparable with theirs. The reference is whatever the
dataset says it is: WebMainBench's comes from human page annotations, Marin's extractor eval set's from an LLM.
"""

import argparse
import collections
import gzip
import json
import statistics


def ngrams(tokens, n):
    return collections.Counter(tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1))


def rouge_n(reference_tokens, predicted_tokens, n):
    ref, pred = ngrams(reference_tokens, n), ngrams(predicted_tokens, n)
    overlap = sum((ref & pred).values())
    precision = overlap / max(sum(pred.values()), 1)
    recall = overlap / max(sum(ref.values()), 1)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def load_predictions(path):
    rows = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                rows[row['idx']] = row
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('dataset')
    parser.add_argument('predictions', nargs='+', metavar='NAME=PREDICTIONS')
    parser.add_argument('-n', type=int, default=5, help='n-gram length (default: 5, as in the paper and Marin)')
    parser.add_argument('--by', default='snapshot', help='dataset field to break scores down by (default: snapshot, '
                                                         'which wmb_convert.py fills with the difficulty level)')
    parser.add_argument('--json', help='also write the summary to this file')
    args = parser.parse_args()

    import jieba
    jieba.setLogLevel(60)

    with gzip.open(args.dataset, 'rt', encoding='utf-8') as f:
        docs = [json.loads(line) for line in f if line.strip()]
    references = [jieba.lcut(d.get('final_output') or '') for d in docs]

    summary = {}
    print(f'{"name":20s} {"docs":>6s} {"P":>7s} {"R":>7s} {"F1":>7s} {"empty":>6s} {"errors":>6s} {"ms/doc":>7s}')
    for spec in args.predictions:
        name, _, path = spec.partition('=')
        rows = load_predictions(path)
        if len(rows) != len(docs):
            raise SystemExit(f'{path}: {len(rows)} predictions for {len(docs)} documents')
        scores, groups = [], collections.defaultdict(list)
        for i, doc in enumerate(docs):
            prediction = rows[i].get('prediction') or ''
            if not doc.get('final_output', '').strip() and not prediction.strip():
                score = (1.0, 1.0, 1.0)
            else:
                score = rouge_n(references[i], jieba.lcut(prediction), args.n)
            scores.append(score)
            groups[str(doc.get(args.by))].append(score[2])
        p, r, f1 = (statistics.fmean(s[k] for s in scores) for k in range(3))
        empty = sum(not (rows[i].get('prediction') or '').strip() for i in range(len(docs)))
        errors = sum(bool(rows[i].get('error')) for i in range(len(docs)))
        ms = statistics.fmean(rows[i]['elapsed_ms'] for i in range(len(docs)))
        print(f'{name:20s} {len(docs):6d} {p:7.4f} {r:7.4f} {f1:7.4f} {empty:6d} {errors:6d} {ms:7.2f}')
        summary[name] = dict(docs=len(docs), precision=p, recall=r, f1=f1, empty=empty, errors=errors,
                             ms_per_doc=ms, f1_by=dict((k, statistics.fmean(v)) for k, v in sorted(groups.items())))

    print(f'\nROUGE-{args.n} F1 by {args.by}:')
    keys = sorted({k for s in summary.values() for k in s['f1_by']})
    print(f'{"name":20s} ' + ' '.join(f'{k[:9]:>9s}' for k in keys))
    for name, s in summary.items():
        print(f'{name:20s} ' + ' '.join(f'{s["f1_by"].get(k, float("nan")):9.4f}' for k in keys))
    print('\nms/doc for rp-bench comes from its threads; set RAYON_NUM_THREADS=1 to compare it with Python.')

    if args.json:
        with open(args.json, 'w') as f:
            json.dump(dict(dataset=args.dataset, n=args.n, results=summary), f, indent=2)


if __name__ == '__main__':
    main()
