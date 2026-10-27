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

## When to run what

| change | run | pass criteria |
|---|---|---|
| A speedup to the Cython extractor | `--warcs 3 --limit 8000` while iterating, then the full run | `0` differing on every WARC; speedup reported on `compare-all.txt` |
| A change meant to alter output | full run with `--wmb` | F1 and recall on WebMainBench at least as good as before; differing records explained by examples |
| Deciding whether to adopt `marin-rust` | full run with `--wmb`, plus Marin's test split if you can read it | faithfulness near 100% with no invented text in `review.md`; its drops in `review.md` mostly boilerplate; quality gain worth the time per record |

Report results with the commit of each setup, the machine, and the harness command line.
