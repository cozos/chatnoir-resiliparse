# Extraction Harness Runbook

How to show, with numbers anyone can reproduce, how fast each HTML extraction setup is, whether a change keeps the
output identical, and how good each setup's output is. `harness.sh` runs all of it; this page says what it runs, on
which data, and how to read the results.

## What it answers

1. **Is this fork a pure speedup?** `ours` must produce byte-identical text to upstream v1.0.9 on every record, and
   the harness reports how much less CPU time it takes.
2. **What does Marin's extractor cost?** `marin-rust` time per record against upstream on the same records.
3. **Is Marin's extractor correct on our crawl data?** Its output can't be compared with upstream's for
   equality, because it keeps different text on purpose. Two checks that need no labels instead: every line it
   outputs must be on the page (faithfulness), and where it keeps more or less than upstream is measured and sampled
   for a person to judge (coverage).
4. **Is Marin's extractor better?** Quality of every setup against human-annotated references (WebMainBench).

## Setups

| name | what it is | how the harness builds it | output |
|---|---|---|---|
| `upstream` | Upstream Resiliparse v1.0.9, `extract_plain_text(main_content=True)` | `build.sh upstream v1.0.9`, from source like the others | plain text |
| `ours` | This fork's Cython extractor (PR #1's speedups) | `build.sh ours <ref>` (default `HEAD`) | plain text, must equal `upstream` |
| `marin-rust` | Marin's learned extractor, `resiliparse-rs/src/parse/html/extract.rs`, with the champion random forest (`benchmark-extract/stack_rf8.json`) and the fastText model it uses as a feature | `cargo build` of Marin's runner `benchmark-extract/rp-bench`, run with `--mode para --threshold 0.60` as in Marin's README | Markdown-like text |

There is no "Marin plus our speedups" setup: our speedups are in the Cython extractor, and Marin's extractor is
separate Rust code, so nothing stacks. Speeding up `marin-rust` would mean optimizing `extract.rs` itself. Marin's
older Cython fork (the 2025 Markdown datasets) is covered by `marin/run_all.sh`, not here.

## Data

**Common Crawl WARCs, for speed and identical output.** `warcs.tsv` lists 18 WARC files (18.5 GB), committed so every
run uses the same ones. `warcs.py make` chose them: one crawl per year for 2013 to 2022 (the years of the DCLM pool
the Generative Curation paper used) and two per year from 2023 (after Marin's training data, and closer to what we
crawl now), with the file inside each crawl picked by a hash of the crawl name. Web HTML changed a lot over those
years, so spreading by year matters more than the number of files. The harness reads the first `--limit` HTML
records of each file (default 8,000), selected the same way as DatologyAI's ingest job.

**WebMainBench, for quality.** [WebMainBench](https://huggingface.co/datasets/opendatalab/WebMainBench) (Apache-2.0)
has 7,809 pages whose main content people marked block by block; the reference text is built from those blocks.
The harness keeps the English pages with Marin's `benchmark-extract/wmb_convert.py`. The dataset also has a
545-page sample, `WebMainBench_545.jsonl`, which is enough for a smoke test.

**What not to use.** Random Common Crawl pages can't measure quality, because nothing says what the right output
is. Marin's extractor eval set (`gs://marin-us-central2/datasets/extractor_eval_set/medium_12k`) has references
written by an LLM, not people, and its 10,000-page train split is what Marin's model was fit to. If you can read
it, score its 1,000-page test split only, with `quality.py`, and report it next to WebMainBench, not instead of it.

## Run it

The repository's Dockerfile has the toolchain (Python 3.11, Rust, CMake, compilers). On an x86-64 machine leave
`TARGET_ARCH` out; on Apple silicon pass `aarch64`.

```bash
docker build --build-arg TARGET_ARCH=aarch64 -t resiliparse-dev .
docker run --rm -it -v "$PWD":/src -v rp-vcpkg:/vcpkg -v rp-bench:/bench resiliparse-dev bash

# inside the container
export PATH=/opt/python/cp311-cp311/bin:$PATH && pip install -q uv
dnf install -y clang-devel    # libclang, for the Rust bindings resiliparse-rs generates
git config --global --add safe.directory '*'
[ -x /vcpkg/vcpkg ] || { git clone https://github.com/microsoft/vcpkg /vcpkg && /vcpkg/bootstrap-vcpkg.sh -disableMetrics; }
export VCPKG_ROOT=/vcpkg BENCH_DIR=/bench
curl -fLO https://huggingface.co/datasets/opendatalab/WebMainBench/resolve/main/webmainbench.jsonl
cd /src
```

Smoke test (one WARC, 500 records, the 545-page WebMainBench sample; the first run spends most of its time building
dependencies):

```bash
curl -fLO https://huggingface.co/datasets/opendatalab/WebMainBench/resolve/main/WebMainBench_545.jsonl
benchmarks/html2text/harness.sh --warcs 1 --limit 500 --wmb WebMainBench_545.jsonl
```

Full run (all 18 WARCs, 8,000 records each, all of WebMainBench):

```bash
benchmarks/html2text/harness.sh --wmb webmainbench.jsonl
```

To test a change, commit it and pass its ref: `--ours my-branch`. Outputs land in `$BENCH_DIR/harness`:

| file | contents |
|---|---|
| `warcs/<crawl>/compare.txt` | speed and differing records for one WARC |
| `compare-all.txt` | the same over all WARCs |
| `checks.txt`, `checks.json` | faithfulness and coverage of `marin-rust`, overall and by year, per record in the JSON |
| `review.md` | a fixed random sample of flagged records, upstream and Marin side by side, for a person to read |
| `quality-wmb.txt`, `quality-wmb.json` | quality on WebMainBench |
| `*.predictions.jsonl` | every output, for reading examples |

Without Docker, follow the set-up section of `README.md` (vcpkg, uv, Python 3.11), install Rust and libclang, and
run the same commands from the repository root.

## Read the results

`compare` prints one row per setup, relative to the first (`upstream`):

- **differing**: records whose output differs from upstream. For `ours` it must be `0` on every WARC; anything
  else is a bug, whatever the speedup. For `marin-rust` it is close to the number of records and says nothing: a
  different algorithm is expected to give different text.
- **total, ms/rec, speedup**: CPU time. For `upstream` and `ours` it is process CPU time, split into encoding
  detection, parsing and extraction, best of two runs. For `marin-rust` it is rp-bench's per-record time on one
  thread, covering parsing and extraction together; encoding detection is done beforehand by `bench.py export`,
  and loading the fastText model is not counted. Treat the `marin-rust` speedup as approximate.
- **chars, empty**: total output size and records with no output. A setup that keeps more text has more chars;
  that is neither good nor bad until quality says which text it kept.

`checks.py` prints, for `marin-rust` on the same Common Crawl records:

- **faithful**: the share of its output text found on the page. "On the page" means the page's text and
  `<title>` plus meta descriptions, built by Python's own HTML parser, so it depends on neither extractor. Lines are
  compared on letters and digits only (no whitespace, punctuation or Markdown marks), and lines under 20 of those
  are skipped. A rule-based extractor should be close to 100%. Lines Marin repaired from mojibake on the page
  (UTF-8 read as Windows-1252, e.g. "mÃ¶chte" to "möchte") count as faithful and are reported separately. What's
  left is usually lines joined from table cells or labels that aren't next to each other in the HTML, and text in
  legacy East Asian encodings that the repair garbles; anything invented is a bug. `review.md` lists examples.
- **up kept**: the share of upstream's word 5-grams that Marin's output also has, pooled over records. Below 100%
  means Marin drops text upstream keeps: boilerplate if Marin is right, content if it's wrong.
- **M in up**: the share of Marin's 5-grams that upstream's output also has. Below 100% means Marin keeps text
  upstream drops: recovered content (comments, code, tables) or extra boilerplate.
- **M empty, M drops, up empty, M adds**: records where one side keeps far more than the other (thresholds under the
  table). These are the records where the extractors disagree most, and `review.md` samples each kind.

The coverage numbers say where the extractors disagree, not who is right. Deciding that takes reading `review.md`
(and WebMainBench says who is right on average). A fair outcome for Marin is: faithfulness near 100%, most of its
drops being boilerplate when you read the sample, and better WebMainBench precision at similar recall.

`quality.py` prints, for each setup on WebMainBench:

- **P, R, F1**: ROUGE-5 precision, recall and F1 of the output against the reference, averaged over pages. Low
  precision means boilerplate kept; low recall means content dropped. ROUGE-5 is the metric the Generative Curation
  paper uses for WebMainBench (its Table 2), computed the way Marin's `wmb_rouge5.py` does (jieba tokens).
- **by snapshot**: F1 by WebMainBench's difficulty level (`wmb_convert.py` stores it in that field).
- **ms/doc**: wall time per page. `bench.py predict` and rp-bench both time a single page, but on different
  clocks from the WARC runs, so use the WARC runs for speed.

The references are Markdown, so Markdown output (`marin-rust`) gets credit for matching headings and table
pipes, and plain text (`upstream`, `ours`) loses a little precision and recall to formatting alone. Compare recall
first when the question is whether content was kept.

## Other extractors on WebMainBench

The harness covers upstream, this fork and Marin's extractor. Other extractors are scored against the same pages and
with the same scorer by writing their predictions in `quality.py`'s format, one script each:

| script | extractor | why it is a useful row |
|---|---|---|
| `run_html_text.py` | html-text 0.7.1, all page text | stands in for Common Crawl's WET files (same approach, not their code) |
| `run_justext.py` | jusText 3.0.2, stock English settings | what Nemotron-CC used, and where Marin's paragraph splitting comes from |
| `run_magic.py` | magic-html 0.1.8, as plain text and as Markdown | the best rule-based extractor in the Dripper paper's WebMainBench table |

They read `wmb_en.jsonl.gz`, the English WebMainBench pages a full harness run leaves in `$BENCH_DIR/harness`. Run
them outside the container, from this directory, with the predictions next to the harness's:

```bash
H=$BENCH_DIR/harness    # or copy wmb_en.jsonl.gz and wmb-*.predictions.jsonl out of the rp-bench volume
uv run --python 3.11 --with html-text --with lxml-html-clean \
    python run_html_text.py $H/wmb_en.jsonl.gz $H/wmb-html-text.predictions.jsonl
uv run --python 3.11 --with justext==3.0.2 --with lxml-html-clean \
    python run_justext.py $H/wmb_en.jsonl.gz $H/wmb-justext.predictions.jsonl
uv run --python 3.12 --with magic-html --with html-text --with lxml-html-clean --with markdownify \
    python run_magic.py $H/wmb_en.jsonl.gz $H/wmb-magic-text.predictions.jsonl $H/wmb-magic-md.predictions.jsonl
```

Score them with `quality.py` alongside the harness's own predictions, then compare page by page with `compare.py`,
which also scores "content-only": the same ROUGE-5 after dropping tokens made only of Markdown punctuation from both
sides, so plain-text and Markdown outputs are judged on which text they kept rather than how they formatted it:

```bash
uv run --python 3.11 --with jieba python quality.py $H/wmb_en.jsonl.gz \
    marin-rust=$H/wmb-marin-rust.predictions.jsonl upstream=$H/wmb-upstream.predictions.jsonl \
    html-text=$H/wmb-html-text.predictions.jsonl justext=$H/wmb-justext.predictions.jsonl \
    magic-text=$H/wmb-magic-text.predictions.jsonl magic-md=$H/wmb-magic-md.predictions.jsonl
uv run --python 3.11 --with jieba python compare.py $H/wmb_en.jsonl.gz \
    marin-rust=$H/wmb-marin-rust.predictions.jsonl magic-text=$H/wmb-magic-text.predictions.jsonl \
    --perpage perpage.json
```

Results from 2026-10-28 (harness at 17510ae, 6,647 English pages; times from one process on an Apple-silicon Mac,
and Marin's from rp-bench's threads, so compare them loosely):

| setup | ROUGE-5 F1 | hard | mid | simple | content-only F1 | empty outputs | ms/page |
|---|---|---|---|---|---|---|---|
| marin-rust | 0.692 | 0.593 | 0.706 | 0.780 | 0.780 | 1 | 1.9 |
| upstream | 0.637 | 0.544 | 0.645 | 0.728 | | 63 | 0.75 |
| magic-html, plain text | 0.614 | 0.537 | 0.620 | 0.689 | 0.712 | 390 | 14.6 |
| magic-html, Markdown | 0.580 | 0.494 | 0.581 | 0.672 | 0.628 | 370 | 14.6 |
| jusText | 0.560 | 0.456 | 0.582 | 0.641 | | 1,200 | 6.3 |
| html-text | 0.545 | 0.410 | 0.543 | 0.693 | | 0 | 1.8 |

Things to know when reading these:

- Published numbers for the same extractors (the Dripper paper's Table 2: magic-html 0.714, Trafilatura 0.640,
  Resiliparse 0.629) are on all 7,809 pages through the paper's own pipeline. Upstream lines up with them; magic-html
  does not reproduce with the stock library and markdownify, so quote our row when comparing with Marin.
- Empty outputs are the extractors' own decisions, not failures: magic-html returns `<body></body>` when it judges a
  page to be a list, and stock jusText marks every paragraph of short-line pages as boilerplate.
- Where marin-rust and magic-html differ most is structured pages: Marin's table rewrite and its 400-character
  structured-page rescue in `classify_paragraphs`. The DatologyAI doc tab "magic-html vs Marin's Extractor" has the
  page-by-page breakdown and proposed fixes; the table breakdown there reran Marin's blocks with `blocktool` from the
  `datologyai/boilerplate-labels` repository.

## When to run what

| change | run | pass criteria |
|---|---|---|
| A speedup to the Cython extractor | `--warcs 3 --limit 8000` while iterating, then the full run | `0` differing on every WARC; speedup reported on `compare-all.txt` |
| A change meant to alter output | full run with `--wmb` | F1 and recall on WebMainBench at least as good as before; differing records explained by examples |
| Deciding whether to adopt `marin-rust` | full run with `--wmb`, plus Marin's test split if you can read it | faithfulness near 100% with no invented text in `review.md`; its drops in `review.md` mostly boilerplate; quality gain worth the time per record |

Report results with the commit of each setup, the machine, and the harness command line.
