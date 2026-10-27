"""
Benchmark and compare Resiliparse HTML text extraction on the HTML records of a WARC file.

Run ``dump`` once to extract the HTML records, then ``run`` with each variant's Python (see build.sh) and
``compare`` the results:

    python bench.py dump CC-MAIN-...warc.gz records.bin
    .bench/venvs/upstream/bin/python bench.py run records.bin upstream.json
    .bench/venvs/ours/bin/python bench.py run records.bin ours.json
    python bench.py compare upstream.json ours.json

``run`` times the three stages of the WARC ingest path separately (encoding detection, parsing, extraction)
and records a digest of every extracted text, so ``compare`` can report both speed and output differences.

Marin's Rust extractor has no Python bindings, so harness.sh runs it with its own runner (rp-bench) instead:
``export`` decodes the same records to JSON lines for it, and ``from-rp`` turns its predictions into a result
that ``compare`` accepts. ``predict`` runs a Python variant over a labeled dataset for quality.py.
"""

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import os
import struct
import time

# Extraction configurations: keyword arguments for extract_plain_text(), or a different extraction function
CONFIGS = {
    'main_content': dict(main_content=True),
    'all_text': dict(main_content=False),
    'minimal_html': dict(main_content=True, preserve_formatting='minimal_html'),
    'simplified_dom': dict(main_content=True, function='extract_simplified_dom'),  # Marin's fork only
}


def dump(warc_path, records_path):
    """Write the HTML response records of a WARC as length-prefixed (URL, payload) pairs."""
    from fastwarc.warc import ArchiveIterator, WarcRecordType

    num_records = 0
    with open(warc_path, 'rb') as warc, open(records_path, 'wb') as out:
        # Same record selection as DatologyAI's WARC ingest job
        for record in ArchiveIterator(warc, record_types=WarcRecordType.response, parse_http=True,
                                      auto_decode='all', max_header_len=1024 * 1024):
            content_type = record.http_headers.get('Content-Type')
            if content_type is None or 'html' not in content_type.lower():
                continue
            url = (record.headers.get('WARC-Target-URI') or '').encode()
            html = record.reader.read()
            out.write(struct.pack('<II', len(url), len(html)))
            out.write(url)
            out.write(html)
            num_records += 1
    print(f'{num_records} HTML records written to {records_path}')


def read_records(records_path, limit=None):
    """Read HTML payloads written by dump()."""
    records = []
    with open(records_path, 'rb') as f:
        while header := f.read(8):
            url_len, html_len = struct.unpack('<II', header)
            f.seek(url_len, 1)
            records.append(f.read(html_len))
            if limit and len(records) >= limit:
                break
    return records


def digest(text):
    return hashlib.blake2b(text.encode('utf-8', 'surrogatepass'), digest_size=8).hexdigest()


def export(records_path, out_path, limit):
    """Decode the records that ``run`` uses to JSON lines ({"url", "html"}) for runners that take text, not bytes."""
    from resiliparse.parse.encoding import bytes_to_str, detect_encoding

    num_records = 0
    with gzip.open(out_path, 'wt', encoding='utf-8') as out:
        for html in (r for r in read_records(records_path, limit) if r.strip()):
            text = bytes_to_str(html, detect_encoding(html))
            out.write(json.dumps({'html': text}, ensure_ascii=False) + '\n')
            num_records += 1
    print(f'{num_records} records written to {out_path}')


def from_rp(predictions_path, result_path, name):
    """Turn rp-bench predictions into a ``run`` result. rp-bench times parsing and extraction together, per record."""
    rows = []
    with open(predictions_path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    rows.sort(key=lambda r: r['idx'])
    texts = [r.get('prediction') or '' for r in rows]
    total = sum(r['elapsed_ms'] for r in rows) / 1000
    result = dict(
        resiliparse=name,
        module=predictions_path,
        config='rp-bench',
        records=len(rows),
        seconds=dict(detect=None, parse=None, extract=total, total=total),
        output_chars=sum(len(t) for t in texts),
        empty_outputs=sum(not t.strip() for t in texts),
        errors=sum(bool(r.get('error')) for r in rows),
        digests=[digest(t) for t in texts])
    with open(result_path, 'w') as f:
        json.dump(result, f)
    print(f'{result_path}: {name}, {len(rows)} records, {total:.2f}s ({1000 * total / len(rows):.2f} ms/record)')


def predict(dataset_path, out_path, config):
    """Run the installed Resiliparse over a labeled dataset ({"html", ...} per line), writing rp-bench-style rows."""
    from resiliparse.extract import html2text
    from resiliparse.parse.html import HTMLTree

    kwargs = dict(CONFIGS[config])
    extract = getattr(html2text, kwargs.pop('function', 'extract_plain_text'))
    with gzip.open(dataset_path, 'rt', encoding='utf-8') as f, open(out_path, 'w', encoding='utf-8') as out:
        for idx, line in enumerate(l for l in f if l.strip()):
            html = json.loads(line).get('html') or ''
            t0 = time.perf_counter()
            text = extract(HTMLTree.parse(html), **kwargs)
            elapsed_ms = 1000 * (time.perf_counter() - t0)
            out.write(json.dumps({'idx': idx, 'prediction': text, 'elapsed_ms': elapsed_ms}, ensure_ascii=False) + '\n')
    print(f'{out_path}: resiliparse {importlib.metadata.version("resiliparse")}, {config}, {idx + 1} documents')


def run(records_path, result_path, config, limit, repeat):
    from resiliparse.extract import html2text
    from resiliparse.parse.encoding import detect_encoding
    from resiliparse.parse.html import HTMLTree

    kwargs = dict(CONFIGS[config])
    extract = getattr(html2text, kwargs.pop('function', 'extract_plain_text'))
    records = [r for r in read_records(records_path, limit) if r.strip()]

    best = None
    for _ in range(repeat):
        seconds = dict(detect=0.0, parse=0.0, extract=0.0)
        texts = []
        for html in records:
            t0 = time.process_time()
            encoding = detect_encoding(html)
            t1 = time.process_time()
            tree = HTMLTree.parse_from_bytes(html, encoding)
            t2 = time.process_time()
            texts.append(extract(tree, **kwargs))
            t3 = time.process_time()
            seconds['detect'] += t1 - t0
            seconds['parse'] += t2 - t1
            seconds['extract'] += t3 - t2
        seconds['total'] = sum(seconds.values())
        if best is None or seconds['total'] < best['total']:
            best = seconds

    result = dict(
        resiliparse=importlib.metadata.version('resiliparse'),
        module=html2text.__file__,
        config=config,
        records=len(records),
        seconds=best,
        output_chars=sum(len(t) for t in texts),
        empty_outputs=sum(not t.strip() for t in texts),
        digests=[digest(t) for t in texts])
    with open(result_path, 'w') as f:
        json.dump(result, f)
    print(f'{result_path}: resiliparse {result["resiliparse"]}, {config}, {len(records)} records, '
          f'{best["total"]:.2f}s ({1000 * best["total"] / len(records):.2f} ms/record)')


def merge(out_path, result_paths):
    """Combine one variant's results on several WARCs into one result: times add up, digests are concatenated."""
    merged = None
    for path in result_paths:
        with open(path) as f:
            r = json.load(f)
        if merged is None:
            merged = r
            continue
        for stage, seconds in r['seconds'].items():
            if seconds is not None:
                merged['seconds'][stage] += seconds
        for key in ('records', 'output_chars', 'empty_outputs', 'errors'):
            if key in r:
                merged[key] = merged.get(key, 0) + r[key]
        merged['digests'] += r['digests']
    with open(out_path, 'w') as f:
        json.dump(merged, f)
    print(f'{out_path}: {len(result_paths)} results, {merged["records"]} records')


def compare(result_paths):
    """Print timing and output differences of each result relative to the first one."""
    results = []
    for path in result_paths:
        with open(path) as f:
            results.append((path, json.load(f)))
    base_path, base = results[0]

    print(f'{"result":24s} {"version":>18s} {"config":>14s} {"detect":>7s} {"parse":>7s} {"extract":>8s} '
          f'{"total":>7s} {"ms/rec":>7s} {"speedup":>8s} {"differing":>10s} {"chars":>9s} {"empty":>6s}')
    stage = lambda v, width: f'{v:{width}.2f}' if v is not None else f'{"-":>{width}s}'
    for path, r in results:
        s = r['seconds']
        if r['records'] != base['records']:
            differing = 'n/a'
        else:
            differing = str(sum(a != b for a, b in zip(base['digests'], r['digests'])))
        label = os.path.relpath(path, os.path.dirname(base_path))
        print(f'{label:24s} {r["resiliparse"]:>18s} {r["config"]:>14s} {stage(s["detect"], 7)} {stage(s["parse"], 7)} '
              f'{s["extract"]:8.2f} {s["total"]:7.2f} {1000 * s["total"] / r["records"]:7.2f} '
              f'{base["seconds"]["total"] / s["total"]:7.2f}x {differing:>10s} '
              f'{r["output_chars"] / 1e6:8.2f}M {r["empty_outputs"]:6d}')
    print(f'\nSpeedup and differing outputs are relative to {base_path}.')
    if any(r['seconds']['parse'] is None for _, r in results):
        print('rp-bench results time parsing and extraction together, without encoding detection (done by export).')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)

    p = commands.add_parser('dump', help='extract the HTML records of a WARC file')
    p.add_argument('warc')
    p.add_argument('records')

    p = commands.add_parser('run', help='benchmark the installed Resiliparse on dumped records')
    p.add_argument('records')
    p.add_argument('result')
    p.add_argument('--config', choices=CONFIGS, default='main_content')
    p.add_argument('--limit', type=int, help='use only the first LIMIT records')
    p.add_argument('--repeat', type=int, default=1, help='repeat and keep the fastest run')

    p = commands.add_parser('compare', help='compare run results to the first one')
    p.add_argument('results', nargs='+')

    p = commands.add_parser('merge', help="combine one variant's results on several WARCs")
    p.add_argument('out')
    p.add_argument('results', nargs='+')

    p = commands.add_parser('export', help='decode the records run uses to JSON lines for rp-bench')
    p.add_argument('records')
    p.add_argument('out', help='output .jsonl.gz')
    p.add_argument('--limit', type=int, help='use only the first LIMIT records (same as run --limit)')

    p = commands.add_parser('from-rp', help='turn rp-bench predictions into a run result')
    p.add_argument('predictions')
    p.add_argument('result')
    p.add_argument('--name', default='marin-rust', help='label shown in the version column')

    p = commands.add_parser('predict', help='run the installed Resiliparse over a labeled dataset')
    p.add_argument('dataset', help='.jsonl.gz with an "html" field per line')
    p.add_argument('out', help='output predictions .jsonl')
    p.add_argument('--config', choices=CONFIGS, default='main_content')

    args = parser.parse_args()
    if args.command == 'dump':
        dump(args.warc, args.records)
    elif args.command == 'run':
        run(args.records, args.result, args.config, args.limit, args.repeat)
    elif args.command == 'merge':
        merge(args.out, args.results)
    elif args.command == 'export':
        export(args.records, args.out, args.limit)
    elif args.command == 'from-rp':
        from_rp(args.predictions, args.result, args.name)
    elif args.command == 'predict':
        predict(args.dataset, args.out, args.config)
    else:
        compare(args.results)


if __name__ == '__main__':
    main()
