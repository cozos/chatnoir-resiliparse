"""
Pick and download the fixed set of Common Crawl WARC files the harness runs on.

    python warcs.py make warcs.tsv          # choose the files (already done; the result is committed)
    python warcs.py fetch warcs.tsv DIR     # download them into DIR, checking each file's size

``make`` picks crawls by year from Common Crawl's crawl list, one file per crawl chosen by a hash of the crawl name,
so rerunning it gives the same files. It writes the path, size and ETag of each file. Files on data.commoncrawl.org
never change, so ``fetch`` only needs to check the size; it skips files that are already complete.
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import shutil
import urllib.request

BASE = 'https://data.commoncrawl.org/'
SEED = 'resiliparse-extract-harness-v1'
# One crawl in each year from 2013 to 2022 (the years of the DCLM pool the Generative Curation paper used),
# two in each year from 2023 on (after Marin's training data and closer to what we crawl now).
PER_YEAR = {**{y: 1 for y in range(2013, 2023)}, **{y: 2 for y in range(2023, 2027)}}


def get(url):
    with urllib.request.urlopen(url) as response:
        return response.read()


def head(url):
    request = urllib.request.Request(url, method='HEAD')
    with urllib.request.urlopen(request) as response:
        return int(response.headers['Content-Length']), response.headers.get('ETag', '').strip('"')


def make(manifest_path):
    crawls = json.loads(get('https://index.commoncrawl.org/collinfo.json'))
    by_year = {}
    for crawl in sorted(c['id'] for c in crawls):
        year = int(crawl.split('-')[2])
        by_year.setdefault(year, []).append(crawl)

    rows = []
    for year, count in sorted(PER_YEAR.items()):
        candidates = by_year.get(year, [])
        # Spread the picks across the year's crawls
        picked = [candidates[i * len(candidates) // count] for i in range(min(count, len(candidates)))]
        for crawl in picked:
            paths = gzip.decompress(get(f'{BASE}crawl-data/{crawl}/warc.paths.gz')).decode().split()
            index = int(hashlib.sha256(f'{SEED}/{crawl}'.encode()).hexdigest(), 16) % len(paths)
            size, etag = head(BASE + paths[index])
            rows.append((crawl, paths[index], size, etag))
            print(f'{crawl}: {paths[index]} ({size / 1e9:.2f} GB)')

    with open(manifest_path, 'w') as f:
        f.write('# crawl\tpath\tbytes\tetag  (made by warcs.py make; see RUNBOOK.md)\n')
        for row in rows:
            f.write('\t'.join(map(str, row)) + '\n')
    print(f'{len(rows)} files, {sum(r[2] for r in rows) / 1e9:.1f} GB, written to {manifest_path}')


def read_manifest(manifest_path, limit=None):
    with open(manifest_path) as f:
        rows = [line.rstrip('\n').split('\t') for line in f if line.strip() and not line.startswith('#')]
    return [(crawl, path, int(size)) for crawl, path, size, _ in rows][:limit]


def fetch(manifest_path, out_dir, limit):
    os.makedirs(out_dir, exist_ok=True)
    for crawl, path, size in read_manifest(manifest_path, limit):
        target = os.path.join(out_dir, os.path.basename(path))
        if os.path.exists(target) and os.path.getsize(target) == size:
            print(f'{target}: present')
            continue
        print(f'{target}: downloading {size / 1e9:.2f} GB')
        with urllib.request.urlopen(BASE + path) as response, open(target + '.part', 'wb') as out:
            shutil.copyfileobj(response, out, length=io.DEFAULT_BUFFER_SIZE * 256)
        if os.path.getsize(target + '.part') != size:
            raise SystemExit(f'{target}: expected {size} bytes, got {os.path.getsize(target + ".part")}')
        os.replace(target + '.part', target)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('make', help='choose the files and write the manifest')
    p.add_argument('manifest')
    p = commands.add_parser('fetch', help='download the files in the manifest')
    p.add_argument('manifest')
    p.add_argument('dir')
    p.add_argument('--limit', type=int, help='only the first LIMIT files')
    p = commands.add_parser('list', help='print the file names in the manifest')
    p.add_argument('manifest')
    p.add_argument('--limit', type=int)
    args = parser.parse_args()
    if args.command == 'make':
        make(args.manifest)
    elif args.command == 'fetch':
        fetch(args.manifest, args.dir, args.limit)
    else:
        for crawl, path, _ in read_manifest(args.manifest, args.limit):
            print(f'{crawl}\t{os.path.basename(path)}')


if __name__ == '__main__':
    main()
