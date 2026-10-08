"""Page extraction, robots parsing, segmentation and decode fallbacks; no sockets."""

import pytest

from app.ai.reach import ReachFetchError
from app.ai.reach_transport import decode_body
from app.domain.research_index import (
    extract_page,
    iter_feed_links,
    iter_sitemap_locations,
    normalize_url,
    parse_robots,
    segment_text,
)

HOMEPAGE = """<html><head><title>示例气泵站</title><style>.x{color:red}</style></head>
<body><h1>首页</h1><script>fetch('/evil')</script><p>欢迎来到示例站点。</p>
<a href="/docs">文档</a><a href="/docs#section">重复</a>
<a href="https://other.example.com/x">外站</a><a href="/login">登录</a>
<a href="mailto:a@b.com">邮件</a></body></html>"""


def test_decode_body_prefers_declared_charset_then_gb18030() -> None:
    assert decode_body("无刷".encode(), "utf-8") == "无刷"
    # A Chinese page served without a header charset still decodes.
    assert decode_body("无刷电机".encode("gb18030"), None) == "无刷电机"
    # A wrong declared charset falls back instead of failing.
    assert decode_body("中文".encode("gb18030"), "utf-8") == "中文"


def test_decode_body_fails_closed_on_undecodable_bytes() -> None:
    with pytest.raises(ReachFetchError):
        decode_body(b"\xff\xfe\xfa\xfb\x00\x01\x02", "utf-8")


def test_normalize_url_drops_fragments_and_credentials() -> None:
    assert normalize_url("HTTPS://Example.com:443/a?b=1#frag") == "https://example.com/a?b=1"
    assert normalize_url("http://example.com:8080/x") == "http://example.com:8080/x"
    assert normalize_url("javascript:alert(1)") == ""
    assert normalize_url("not a url") == ""


def test_extract_page_drops_hidden_markup_and_collects_links() -> None:
    page = extract_page(HOMEPAGE, base_url="https://example.com/")
    assert page.title == "示例气泵站"
    assert "示例站点" in page.text and "fetch" not in page.text
    assert "https://example.com/docs" in page.links  # fragment variant deduped
    assert "https://other.example.com/x" in page.links
    assert "mailto:a@b.com" not in page.links


def test_extract_page_resolves_relative_links_against_base() -> None:
    page = extract_page('<a href="../spec.html">s</a>', base_url="https://example.com/docs/index")
    assert "https://example.com/spec.html" in page.links


def test_extract_page_prioritizes_main_and_preserves_specs_without_navigation_noise() -> None:
    body = (
        '<title>电动气泵评测</title><header role="banner">会员优惠</header>'
        '<nav><a href="/products">全部商品</a></nav><main><h1>桨板气泵</h1>'
        '<div class="cookie-banner">同意追踪</div><p>最大压力 <strong>20</strong> PSI</p>'
        "<table><tr><td>供电</td><td>12V</td></tr><tr><td>重量</td><td>1.2kg</td></tr></table>"
        '<p hidden>隐藏促销</p><p style="display:none">订阅优惠</p>'
        "<script>伪造规格</script></main><footer>版权菜单</footer>"
    )
    page = extract_page(body, base_url="https://review.example.com/pump")
    assert page.title == "电动气泵评测"
    assert "最大压力 20 PSI" in page.text
    assert "供电 12V\n重量 1.2kg" in page.text
    assert not any(
        word in page.text
        for word in [
            "会员优惠",
            "全部商品",
            "同意追踪",
            "隐藏促销",
            "订阅优惠",
            "伪造规格",
            "版权菜单",
        ]
    )
    assert "https://review.example.com/products" in page.links


def test_extract_page_handles_article_fallback_void_tags_and_missing_title() -> None:
    body = (
        "<div>商品菜单</div><article><h1>海边气泵评测</h1>"
        '<p>12V<br/>20PSI<img src="pump.jpg"/>，未测续航</p>'
        "<aside>推荐文章</aside></article>"
    )
    page = extract_page(body, base_url="https://review.example.com/pump")
    assert page.title == "海边气泵评测"
    assert "12V\n20PSI，未测续航" in page.text
    assert "商品菜单" not in page.text and "推荐文章" not in page.text


def test_extract_page_does_not_drop_plain_text_or_unmarked_specs() -> None:
    assert (
        extract_page("压力20PSI\n供电12V", base_url="https://example.com/").text
        == "压力20PSI\n供电12V"
    )
    page = extract_page(
        '<meta property="og:title" content="官方规格"/><div>压力20PSI</div><div>供电12V</div>',
        base_url="https://example.com/",
    )
    assert page.title == "官方规格" and page.text == "压力20PSI\n供电12V"


def test_embedded_video_documents_cannot_replace_the_article_title() -> None:
    body = (
        "<html><body><article><h1>桨板气泵选购</h1><h1>品牌比较</h1>"
        "<p>公开规格20PSI</p><iframe><html><head><title>YouTube视频标题</title>"
        '<meta property="og:title" content="视频元标题"/></head>'
        "<body><h1>视频频道</h1></body></html></iframe>"
        "<title>另一个嵌入标题</title></article></body></html>"
    )
    page = extract_page(body, base_url="https://brand.example/blog")
    assert page.title == "桨板气泵选购"
    assert "公开规格20PSI" in page.text
    assert not any(text in page.text for text in ("视频标题", "视频频道", "嵌入标题"))


def test_parse_robots_groups_prefixes_delay_and_sitemaps() -> None:
    rules = parse_robots(
        "User-agent: other\nDisallow: /x\n\n"
        "User-agent: *\nCrawl-delay: 5\nDisallow: /private\nAllow: /private/public\n"
        "Sitemap: https://example.com/sitemap.xml"
    )
    assert rules.crawl_delay_seconds == 5
    assert rules.permits("/docs") and rules.permits("/private/public")
    assert not rules.permits("/private/secret")
    assert "https://example.com/sitemap.xml" in rules.sitemap_urls


def test_parse_robots_without_our_agent_allows_everything() -> None:
    rules = parse_robots("User-agent: greedy\nDisallow: /")
    assert rules.permits("/anything")


def test_parse_robots_root_disallow_blocks_everything() -> None:
    rules = parse_robots("User-agent: *\nDisallow: /")
    assert not rules.permits("/docs")


def test_segment_text_splits_chinese_for_simple_tsvector() -> None:
    segmented = segment_text("无刷电机气泵规格")
    assert "无刷电机" in segmented.split() and "气泵" in segmented.split()


def test_iter_feed_links_reads_rss_and_atom() -> None:
    rss = "<rss><channel><item><link>/a</link></item><link>/b</link></channel></rss>"
    assert iter_feed_links(rss, "https://example.com/") == (
        "https://example.com/a",
        "https://example.com/b",
    )
    atom = '<feed><link href="/c"/></feed>'
    assert iter_feed_links(atom, "https://example.com/") == ("https://example.com/c",)


def test_iter_sitemap_locations_reads_locs() -> None:
    body = "<urlset><url><loc>https://example.com/x</loc></url><url><loc>bad</loc></url></urlset>"
    assert iter_sitemap_locations(body) == ("https://example.com/x",)
