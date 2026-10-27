"""
Check an extractor whose output is meant to differ from upstream's (Marin's Rust extractor) on Common Crawl records,
without reference text:

- Faithfulness: every line of its output should appear in the page's HTML: its text, including <title>, plus the
  meta descriptions Marin's fallback uses. The page text is built here with Python's own HTML parser, so it depends
  on neither extractor. Lines are compared on letters and digits only, so whitespace, punctuation and Markdown marks
  don't count. A line that isn't there was invented, garbled or joined from pieces that aren't adjacent on the page.
- Coverage: how much of upstream's main-content output it keeps, and how much of its own output upstream also has,
  as shares of word 5-grams. Records where one side keeps much more than the other are flagged.

    python checks.py HARNESS_DIR [--sample 50]

HARNESS_DIR is harness.sh's output directory; each warcs/<crawl>/ in it needs records.jsonl.gz (bench.py export),
upstream.texts.jsonl.gz and marin-rust.predictions.jsonl. Writes checks.json, and review.md with a fixed random
sample of flagged records and unfaithful lines for a person to read.
"""

import argparse
import collections
import gzip
import html.parser
import json
import multiprocessing
import os
import random
import re
import unicodedata

WORD = re.compile(r'\w+')
# Markdown list and quote marks at the start of a line, including the numbers of ordered list items
MARKER = re.compile(r'^\s*(?:[-*+>#]+|\d{1,3}[.)])\s+')
MIN_LINE = 20      # letters and digits; shorter lines (bullets, labels, numbers) are too common to tell anything
MIN_CHARS = 500    # a side needs this much output before its coverage counts as dropping or adding content
SEED = 'resiliparse-extract-checks-v1'


def squash(text):
    """Letters and digits only, case-folded: what two renderings of the same text have in common."""
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


class PageText(html.parser.HTMLParser):
    """Every text node of a page, plus the attribute text Marin's fallbacks can output (meta descriptions)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            attrs = dict(attrs)
            if (attrs.get('name') or attrs.get('property') or '').lower() in ('description', 'og:description'):
                self.parts.append(attrs.get('content') or '')

    def handle_data(self, data):
        self.parts.append(data)


def page_text(html_text):
    parser = PageText()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # html.parser gives up on some malformed pages; fall back to the raw HTML
        return html_text
    return '\n'.join(parser.parts)


def shingles(text, n=5):
    words = WORD.findall(text.casefold())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def read_texts(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return [json.loads(line) for line in f]


def read_pages(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return [json.loads(line) for line in f]


def read_predictions(path):
    rows = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                rows[row['idx']] = row
    return [rows[i] for i in range(len(rows))]


def check_record(args):
    html_text, upstream, marin = args
    page = squash(page_text(html_text))
    lines = [l for l in marin.splitlines() if len(squash(MARKER.sub('', l))) >= MIN_LINE]
    unfaithful = [l for l in lines if squash(MARKER.sub('', l)) not in page]
    up, ma = shingles(upstream), shingles(marin)
    common = len(up & ma)
    flags = []
    if len(marin.strip()) < 50 and len(upstream) >= MIN_CHARS:
        flags.append('marin_empty')
    elif len(upstream) >= MIN_CHARS and up and common / len(up) < 0.5:
        flags.append('marin_drops_most')
    if len(upstream.strip()) < 50 and len(marin) >= MIN_CHARS:
        flags.append('upstream_empty')
    elif len(marin) >= MIN_CHARS and ma and common / len(ma) < 0.5:
        flags.append('marin_adds_most')
    if sum(len(squash(l)) for l in unfaithful) >= 0.2 * max(1, sum(len(squash(l)) for l in lines)):
        flags.append('unfaithful')
    return dict(
        lines=len(lines), line_chars=sum(len(squash(l)) for l in lines),
        unfaithful_lines=len(unfaithful), unfaithful_chars=sum(len(squash(l)) for l in unfaithful),
        up_shingles=len(up), marin_shingles=len(ma), common_shingles=common,
        up_chars=len(upstream), marin_chars=len(marin), flags=flags), unfaithful


def pooled(rows):
    s = lambda k: sum(r[k] for r in rows)
    return dict(
        records=len(rows),
        faithful_share=1 - s('unfaithful_chars') / max(1, s('line_chars')),
        records_with_unfaithful=sum(r['unfaithful_lines'] > 0 for r in rows),
        upstream_kept=s('common_shingles') / max(1, s('up_shingles')),
        marin_in_upstream=s('common_shingles') / max(1, s('marin_shingles')),
        upstream_chars=s('up_chars'), marin_chars=s('marin_chars'),
        flags=dict(collections.Counter(f for r in rows for f in r['flags'])))


def excerpt(text, limit=700):
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + ' …'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('harness_dir')
    parser.add_argument('--sample', type=int, default=50, help='flagged records to put in review.md (default: 50)')
    args = parser.parse_args()

    rows, examples = [], []
    with multiprocessing.Pool() as pool:
        for crawl in sorted(os.listdir(os.path.join(args.harness_dir, 'warcs'))):
            d = os.path.join(args.harness_dir, 'warcs', crawl)
            pages = read_pages(os.path.join(d, 'records.jsonl.gz'))
            upstream = read_texts(os.path.join(d, 'upstream.texts.jsonl.gz'))
            marin = read_predictions(os.path.join(d, 'marin-rust.predictions.jsonl'))
            if not len(pages) == len(upstream) == len(marin):
                raise SystemExit(f'{d}: {len(pages)} pages, {len(upstream)} upstream, {len(marin)} marin records')
            urls = [p.get('url') for p in pages]
            marin = [m.get('prediction') or '' for m in marin]
            work = zip((p['html'] for p in pages), upstream, marin)
            for i, (row, unfaithful) in enumerate(pool.imap(check_record, work, chunksize=64)):
                row.update(crawl=crawl, idx=i, url=urls[i])
                rows.append(row)
                examples.append((upstream[i], marin[i], unfaithful))

    by_year = collections.defaultdict(list)
    for r in rows:
        by_year[r['crawl'].split('-')[2]].append(r)
    summary = dict(overall=pooled(rows), by_year={y: pooled(v) for y, v in sorted(by_year.items())})
    with open(os.path.join(args.harness_dir, 'checks.json'), 'w') as f:
        json.dump(dict(summary=summary, records=rows), f)

    o = summary['overall']
    print(f'{o["records"]} records, Marin\'s extractor against upstream\'s main content and the page\'s HTML text\n')
    print(f'Faithfulness: {100 * o["faithful_share"]:.2f}% of output text (lines of {MIN_LINE}+ letters and digits) '
          f'is on the page; {o["records_with_unfaithful"]} records have at least one line that isn\'t')
    print(f'Coverage: Marin keeps {100 * o["upstream_kept"]:.1f}% of upstream\'s word 5-grams; '
          f'{100 * o["marin_in_upstream"]:.1f}% of Marin\'s are also in upstream\'s output')
    print(f'Output size: upstream {o["upstream_chars"] / 1e6:.1f}M chars, Marin {o["marin_chars"] / 1e6:.1f}M\n')
    print(f'{"year":6s} {"records":>8s} {"faithful":>9s} {"unfaith.":>9s} {"up kept":>8s} {"M in up":>8s} '
          f'{"M empty":>8s} {"M drops":>8s} {"up empty":>9s} {"M adds":>7s}')
    for year, s in summary['by_year'].items():
        fl = s['flags']
        print(f'{year:6s} {s["records"]:8d} {100 * s["faithful_share"]:8.2f}% {s["records_with_unfaithful"]:9d} '
              f'{100 * s["upstream_kept"]:7.1f}% {100 * s["marin_in_upstream"]:7.1f}% {fl.get("marin_empty", 0):8d} '
              f'{fl.get("marin_drops_most", 0):8d} {fl.get("upstream_empty", 0):9d} {fl.get("marin_adds_most", 0):7d}')
    print('\nFlags: M empty = Marin outputs under 50 chars where upstream has 500+; M drops = Marin keeps under half '
          'of upstream\'s 5-grams; up empty / M adds = the same the other way round.')

    # A fixed sample of each kind of flagged record, for a person to judge which side is right
    rng = random.Random(SEED)
    kinds = ['marin_empty', 'marin_drops_most', 'upstream_empty', 'marin_adds_most', 'unfaithful']
    per_kind = max(1, args.sample // len(kinds))
    with open(os.path.join(args.harness_dir, 'review.md'), 'w') as f:
        f.write('# Records to review\n\nA fixed random sample of each kind of flagged record (checks.py). For each, '
                'decide whether upstream or Marin kept the right content.\n')
        for kind in kinds:
            picked = [i for i, r in enumerate(rows) if kind in r['flags']]
            picked = sorted(rng.sample(picked, min(per_kind, len(picked))))
            f.write(f'\n## {kind} ({sum(kind in r["flags"] for r in rows)} records, showing {len(picked)})\n')
            for i in picked:
                r = rows[i]
                up, ma, unfaithful = examples[i]
                f.write(f'\n### {r["crawl"]} #{r["idx"]} · {r["url"]}\n\n'
                        f'upstream {r["up_chars"]} chars, Marin {r["marin_chars"]} chars, Marin keeps '
                        f'{100 * r["common_shingles"] / max(1, r["up_shingles"]):.0f}% of upstream\'s 5-grams\n\n'
                        f'**Upstream:**\n\n```\n{excerpt(up)}\n```\n\n**Marin:**\n\n```\n{excerpt(ma)}\n```\n')
                if unfaithful:
                    f.write('\n**Marin lines not on the page:**\n\n' +
                            ''.join(f'- `{excerpt(l, 200)}`\n' for l in unfaithful[:5]))
    print(f'\nWrote {os.path.join(args.harness_dir, "checks.json")} and review.md')


if __name__ == '__main__':
    main()
