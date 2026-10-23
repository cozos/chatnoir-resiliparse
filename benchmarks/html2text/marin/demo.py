"""Small, targeted demonstrations. Run with each variant's Python: <venv>/bin/python demo.py"""
import json, os, sys
from resiliparse.extract import html2text as h2t
from resiliparse.parse.html import HTMLTree
import importlib.metadata as md

def plain(html):
    return h2t.extract_plain_text(HTMLTree.parse(html), main_content=True)

# 1. Marin's list rule: a content list directly under <main> (shallow, so upstream's "body_depth < 4" drops it)
LIST = '''<html><body><main><h1>How to repot a plant</h1>
<ul><li>Water the plant a day before repotting it.</li><li>Pick a pot one size larger than the old one.</li>
<li>Loosen the roots gently before moving the plant.</li></ul></main></body></html>'''

# 2. Depth-gated rules (sign-in, post meta, social, footer) on a normally nested blog post
BLOG = '''<html><body><div class="page"><div class="wrap"><div class="content"><article>
<h1>Repotting succulents</h1>
<div class="post-meta">Posted by Jane on 1 March 2024 in Gardening</div>
<p>Succulents need a fast-draining soil mix and a pot with a drainage hole. Repot them in spring.</p>
<div class="social-share">Share on Facebook Share on Twitter Pin it</div>
<div class="login-box">Log in to comment</div>
<footer><p>Article footnote: soil mix recipe is 1 part perlite to 1 part potting soil.</p></footer>
</article></div></div></div></body></html>'''

result = dict(version=md.version('resiliparse'))
result['list_plain'] = plain(LIST)
result['blog_plain'] = plain(BLOG)
if hasattr(h2t, 'extract_simplified_dom'):
    result['blog_simplified_dom'] = h2t.extract_simplified_dom(BLOG, preserve_formatting=True, main_content=True)

    # 3. Memory: RSS growth over repeated calls on the same page
    def rss_mb():
        with open('/proc/self/statm') as f:
            return int(f.read().split()[1]) * os.sysconf('SC_PAGE_SIZE') / 2**20
    page = BLOG.replace('<p>Succulents', '<p>' + 'Succulents need well-drained soil. ' * 1500 + '<p>Succulents')
    for name, fn in [('extract_plain_text', lambda: h2t.extract_plain_text(page, main_content=True)),
                     ('extract_simplified_dom', lambda: h2t.extract_simplified_dom(page, preserve_formatting=True, main_content=True))]:
        fn(); before = rss_mb()
        for _ in range(5000): fn()
        result[f'rss_growth_mb_{name}'] = round(rss_mb() - before, 1)
    result['page_kb'] = round(len(page) / 1024, 1)
print(json.dumps(result, indent=1))
