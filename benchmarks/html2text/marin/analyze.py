"""Compare the outputs written by run_all.sh (run from its output directory).

'Visible text' is upstream 1.0.9 with main_content=False; 'kept %' is the share of its words an output keeps.
"""
import collections, json, re

WORD = re.compile(r'\w+', re.U)
MD_LINK = re.compile(r'!?\[([^\]]*)\]\([^)]*\)')
VARIANTS = ['upstream-2024', 'marin', 'marin-markdown', 'upstream', 'ours']


def load(name):
    with open(f'out-{name}.jsonl') as f:
        return [json.loads(l) for l in f]


def words(text):
    return collections.Counter(w.lower() for w in WORD.findall(MD_LINK.sub(r'\1', text)))


def short_lines(text):
    lines = set()
    for line in MD_LINK.sub(r'\1', text).splitlines():
        line = line.strip().lstrip('-*#|>•0123456789. ').strip().replace('**', '').replace('__', '')
        if 3 <= len(line) <= 60:
            lines.add(line)
    return lines


with open('timings.jsonl') as f:
    timings = {json.loads(l)['out']: json.loads(l) for l in f}
visible = [words(t) for t in load('visible')]
visible_total = sum(sum(c.values()) for c in visible)
outputs = {v: load(v) for v in VARIANTS}
word_counts = {v: [words(t) for t in outputs[v]] for v in VARIANTS}

print(f"{'variant':15s} {'version':>8s} {'CPU s':>8s} {'ms/page':>8s} {'chars':>8s} {'empty':>6s} {'kept %':>7s}")
for v in VARIANTS:
    t, texts = timings[f'out-{v}.jsonl'], outputs[v]
    kept = sum(sum((a & b).values()) for a, b in zip(word_counts[v], visible))
    print(f"{v:15s} {t['version']:>8s} {t['cpu']:8.1f} {1000 * t['cpu'] / t['pages']:8.2f} "
          f"{sum(map(len, texts)) / 1e6:7.1f}M {sum(not x.strip() for x in texts):6d} {100 * kept / visible_total:7.1f}")
print(f'{len(visible)} pages, {visible_total} visible words')


def differing(a, b):
    return sum(x != y for x, y in zip(outputs[a], outputs[b]))


def more_less_similar(a, b):
    """Pages where a has >20% (and >20) more words than b, fewer, or about the same."""
    counts = [0, 0, 0]
    for x, y in zip(word_counts[a], word_counts[b]):
        nx, ny = sum(x.values()), sum(y.values())
        counts[0 if nx > 1.2 * ny + 20 else 1 if ny > 1.2 * nx + 20 else 2] += 1
    return counts


print('\ndiffering pages: marin vs upstream-2024', differing('marin', 'upstream-2024'),
      '| ours vs upstream', differing('ours', 'upstream'))
print('marin vs upstream-2024 (more, fewer, similar words):', more_less_similar('marin', 'upstream-2024'))
print('marin-markdown vs upstream (more, fewer, similar words):', more_less_similar('marin-markdown', 'upstream'))

for a, b in [('marin-markdown', 'upstream'), ('upstream', 'marin-markdown')]:
    lines = collections.Counter()
    for x, y in zip(outputs[a], outputs[b]):
        lines.update(short_lines(x) - short_lines(y))
    print(f'\nShort lines {a} keeps and {b} drops, by number of pages:')
    for line, n in lines.most_common(20):
        print(f'  {n:5d}  {line}')
