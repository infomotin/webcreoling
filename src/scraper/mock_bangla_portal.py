"""
Hermetic Mock Bangla News Portal HTTP Server.
Provides realistic multi-category Bangla news pages, pagination, JSON-LD metadata,
and synthetic image endpoints for offline end-to-end testing and demonstrations.
"""

import io
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from PIL import Image, ImageDraw


# Sample realistic Bangla articles across 5 categories
MOCK_ARTICLES = [
    # 1. Politics
    {
        "id": "pol-01",
        "category": "politics",
        "title": "জাতীয় সংসদের নতুন অধিবেশন শুরু, গুরুত্বপূর্ণ বিল পাসের সম্ভাবনা",
        "author": "নিজস্ব প্রতিবেদক",
        "published_at": "2026-09-20T10:00:00+06:00",
        "summary": "সংসদে নতুন অর্থবিলের ওপর আলোচনা শুরু হয়েছে এবং স্পিকার সকল সংসদ সদস্যকে আলোচনায় অংশ নেওয়ার আহ্বান জানিয়েছেন।",
        "content": (
            "জাতীয় সংসদের বিশেষ অধিবেশন আজ সকালে শুরু হয়েছে। অধিবেশনে দেশের আর্থ-সামাজিক উন্নয়ন, নতুন বাজেট বরাদ্দ "
            "এবং বেশ কয়েকটি গুরুত্বপূর্ণ নীতিগত সংস্কার বিল উত্থাপন করা হবে। স্পিকারের সভাপতিত্বে অধিবেশনের কার্যক্রম "
            "নিয়মতান্ত্রিকভাবে শুরু হয়। সরকারি ও বিরোধী দলের সদস্যরা অধিবেশনে উপস্থিত ছিলেন। দেশের সামগ্রিক অর্থনীতি ও "
            "জনকল্যাণমূলক প্রকল্পগুলোর অগ্রগতি নিয়ে বিস্তারিত আলোচনা অনুষ্ঠিত হয়।"
        ),
        "entities": {"Person": ["স্পিকার"], "Location": ["জাতীয় সংসদ", "ঢাকা"], "Organization": ["সংসদ"]},
    },
    {
        "id": "pol-02",
        "category": "politics",
        "title": "স্থানীয় সরকার নির্বাচনে ভোটারদের ব্যাপক উপস্থিতি",
        "author": "অনলাইন ডেস্ক",
        "published_at": "2026-09-21T14:30:00+06:00",
        "summary": "স্থানীয় সরকার নির্বাচনে সাধারণ মানুষের মাঝে ব্যাপক উৎসাহ ও উদ্দীপনা লক্ষ্য করা গেছে।",
        "content": (
            "দেশের বিভিন্ন অঞ্চলে আজ স্থানীয় সরকার নির্বাচন সুষ্ঠু ও শান্তিপূর্ণ পরিবেশে অনুষ্ঠিত হয়েছে। "
            "সকাল থেকেই ভোটকেন্দ্রগুলোতে নারী ও পুরুষ ভোটারদের দীর্ঘ সারি দেখা যায়। নির্বাচন কমিশনের পক্ষ থেকে "
            "কড়া নিরাপত্তা ব্যবস্থা গ্রহণ করা হয়। কোনো অপ্রীতিকর ঘটনা ছাড়াই ভোটগ্রহণ সম্পন্ন হয় এবং নির্বাচন "
            "পর্যবেক্ষকরা সন্তোষ প্রকাশ করেছেন।"
        ),
        "entities": {"Organization": ["নির্বাচন কমিশন"], "Location": ["বাংলাদেশ"]},
    },

    # 2. Sports
    {
        "id": "spt-01",
        "category": "sports",
        "title": "আন্তর্জাতিক টি-টোয়েন্টি সিরিজে বাংলাদেশের অবিস্মরণীয় জয়",
        "author": "ক্রীড়া প্রতিবেদক",
        "published_at": "2026-09-21T18:00:00+06:00",
        "summary": "মিরপুর শেরেবাংলা স্টেডিয়ামে টানটান উত্তেজনার ম্যাচে বাংলাদেশ শেষ ওভারে নাটকীয় জয় ছিনিয়ে নিয়েছে।",
        "content": (
            "মিরপুর শেরেবাংলা জাতীয় ক্রিকেট স্টেডিয়ামে অনুষ্ঠিত তিন ম্যাচ সিরিজের শেষ টি-টোয়েন্টিতে সফরকারীদের বিরুদ্ধে "
            "৫ উইকেটের এক দুর্দান্ত জয় পেয়েছে বাংলাদেশ। অধিনায়কের অনবদ্য অর্ধশতক এবং শেষ ওভারে বোলারদের নিয়ন্ত্রিত বোলিং "
            "দলের এই জয়ে মূখ্য ভূমিকা রাখে। ম্যাচ শেষে অধিনায়ককে ম্যাচসেরা পুরস্কারে ভূষিত করা হয় এবং দর্শকরা উল্লাসে মেতে ওঠেন।"
        ),
        "entities": {"Person": ["অধিনায়ক"], "Location": ["মিরপুর", "ঢাকা"], "Organization": ["বাংলাদেশ ক্রিকেট দল"]},
    },
    {
        "id": "spt-02",
        "category": "sports",
        "title": "সাফ অনূর্ধ্ব-২০ ফুটবলে চ্যাম্পিয়ন বাংলাদেশ দল",
        "author": "স্পোর্টস ডেস্ক",
        "published_at": "2026-09-19T20:15:00+06:00",
        "summary": "সাফ অনূর্ধ্ব-২০ চ্যাম্পিয়নশিপের ফাইনালে প্রতিপক্ষকে ৩-০ গোলে হারিয়ে শিরোপা জিতেছে বাংলাদেশ দল।",
        "content": (
            "সাফ অনূর্ধ্ব-২০ ফুটবল চ্যাম্পিয়নশিপের ফাইনালে নজরকাড়া নৈপুণ্য দেখিয়ে শিরোপা নিজেদের করে নিয়েছে বাংলাদেশ যুব দল। "
            "প্রথমার্ধে দুটি ও দ্বিতীয়ার্ধে একটি গোল করে প্রতিপক্ষকে পুরোপুরি কোণঠাসা করে ফেলে দলের আক্রমণভাগ। কোচ খেলোয়াড়দের "
            "পরিশ্রম ও শৃঙ্খলার ভূয়সী প্রশংসা করেছেন।"
        ),
        "entities": {"Location": ["বাংলাদেশ", "সাউথ এশিয়া"], "Organization": ["সাফ", "বাংলাদেশ ফুটবল ফেডারেশন"]},
    },

    # 3. Business
    {
        "id": "bus-01",
        "category": "business",
        "title": "রপ্তানি আয়ে ইতিবাচক প্রবৃদ্ধি, তৈরি পোশাকে সর্বোচ্চ আয়",
        "author": "অর্থনীতি বিশ্লেষক",
        "published_at": "2026-09-21T09:00:00+06:00",
        "summary": "চলতি অর্থবছরের প্রথম প্রান্তিকে বাংলাদেশের রপ্তানি আয়ে রেকর্ড প্রবৃদ্ধি অর্জিত হয়েছে।",
        "content": (
            "চলতি অর্থবছরের প্রথম প্রান্তিকে রপ্তানি বাণিজ্যে ব্যাপক ইতিবাচক অগ্রগতি লক্ষ্য করা গেছে। রপ্তানি উন্নয়ন ব্যুরোর "
            "তথ্যমতে, তৈরি পোশাক ও চামড়াজাত পণ্য থেকে রেকর্ড পরিমাণ বৈদেশিক মুদ্রা আয় হয়েছে। ইউরোপ ও আমেরিকার বাজারে চাহিদা "
            "বৃদ্ধির পাশাপাশি পণ্যের বহুমুখীকরণ এই প্রবৃদ্ধিতে বড় ভূমিকা রেখেছে। ব্যবসায়িক সংগঠনগুলো সরকারের নীতিগত সহায়তাকে "
            "ধন্যবাদ জানিয়েছে।"
        ),
        "entities": {"Location": ["ইউরোপ", "আমেরিকা", "বাংলাদেশ"], "Organization": ["রপ্তানি উন্নয়ন ব্যুরো", "বিজিএমইএ"]},
    },
    {
        "id": "bus-02",
        "category": "business",
        "title": "পুঁজিবাজারে লেনদেন বৃদ্ধির সাথে সূচকের ঊর্ধ্বগতি",
        "author": "বাণিজ্য ডেস্ক",
        "published_at": "2026-09-22T11:00:00+06:00",
        "summary": "ঢাকা স্টক এক্সচেঞ্জে আজ দিনভর লেনদেনের পরিমাণ বৃদ্ধি পেয়ে সূচক ইতিবাচক ধারায় অবস্থান করছে।",
        "content": (
            "সপ্তাহের তৃতীয় কার্যদিবসে ঢাকা স্টক এক্সচেঞ্জে (ডিএসই) সূচকের ঊর্ধ্বমুখী প্রবণতা লক্ষ্য করা গেছে। "
            "অধিকাংশ প্রাতিষ্ঠানিক বিনিয়োগকারীর সক্রিয় অংশগ্রহণে বাজারে লেনদেনের পরিমাণ ১ হাজার কোটি টাকা ছাড়িয়েছে। "
            "বিশেষ করে ব্যাংক, আর্থিক প্রতিষ্ঠান এবং তথ্যপ্রযুক্তি খাতের শেয়ারের প্রতি ক্রেতাদের আগ্রহ ছিল সবচেয়ে বেশি।"
        ),
        "entities": {"Organization": ["ঢাকা স্টক এক্সচেঞ্জ", "ডিএসই"], "Location": ["ঢাকা"]},
    },

    # 4. Technology
    {
        "id": "tech-01",
        "category": "technology",
        "title": "কৃত্রিম বুদ্ধিমত্তা ও ভাষা মডেলে বাংলায় নতুন অগ্রগতি",
        "author": "প্রযুক্তি প্রতিবেদক",
        "published_at": "2026-09-22T08:30:00+06:00",
        "summary": "বাংলা ভাষার জন্য বিশেষায়িত ওপেন সোর্স এআই ও ন্যাচারাল ল্যাঙ্গুয়েজ প্রসেসিং পাইপলাইন তৈরি হয়েছে।",
        "content": (
            "বাংলা ভাষার ডিজিটাল তথ্যভাণ্ডার ও কৃত্রিম বুদ্ধিমত্তা (AI) প্রযুক্তির প্রয়োগে এক যুগান্তকারী সাফল্য অর্জিত হয়েছে। "
            "স্থানীয় গবেষকরা তৈরি করেছেন উন্নত বাংলা ল্যাঙ্গুয়েজ মডেল, যা স্বয়ংক্রিয় সংবাদ সারসংক্ষেপ, তথ্য শ্রেণিবিন্যাস "
            "এবং সত্তা নিষ্কাশনে সক্ষম। এটি প্রশাসনিক কাজ ও ই-কমার্সে স্বয়ংক্রিয় যোগাযোগকে আরও সহজ ও গতিশীল করবে।"
        ),
        "entities": {"Organization": ["বাংলাদেশ প্রকৌশল বিশ্ববিদ্যালয়", "তথ্যপ্রযুক্তি বিভাগ"], "Location": ["বাংলাদেশ"]},
    },
    {
        "id": "tech-02",
        "category": "technology",
        "title": "সারাদেশে উচ্চগতির ব্রডব্যান্ড ইন্টারনেট সম্প্রসারণ প্রকল্প",
        "author": "আইটি ডেস্ক",
        "published_at": "2026-09-20T16:45:00+06:00",
        "summary": "গ্রামাঞ্চলে অপটিক্যাল ফাইবার সংযোগ নিশ্চিত করতে নতুন ডিজিটাল কানেক্টিভিটি প্রকল্প হাতে নেওয়া হয়েছে।",
        "content": (
            "দেশের প্রত্যন্ত অঞ্চলের সকল ইউনিয়নে নিরবচ্ছিন্ন উচ্চগতির ইন্টারনেট সেবা পৌঁছে দিতে ব্যাপক উদ্যোগ নেওয়া হয়েছে। "
            "অপটিক্যাল ফাইবার ক্যাবল নেটওয়ার্ক স্থাপনের ফলে গ্রামীণ তরুণ সমাজ ফ্রিল্যান্সিং ও অনলাইন শিক্ষায় আরও বেশি যুক্ত হতে পারবে। "
            "প্রকল্পটি আগামী বছরের মাঝামাঝি পুরোপুরি কার্যকর হবে বলে আশা করা হচ্ছে।"
        ),
        "entities": {"Organization": ["বিটিসিএল", "ডাক ও টেলিযোগাযোগ বিভাগ"], "Location": ["বাংলাদেশ"]},
    },

    # 5. International
    {
        "id": "int-01",
        "category": "international",
        "title": "জাতিসংঘ সাধারণ পরিষদে জলবায়ু পরিবর্তন মোকাবিলায় বৈশ্বিক আহ্বান",
        "author": "আন্তর্জাতিক ডেস্ক",
        "published_at": "2026-09-21T21:00:00+06:00",
        "summary": "নিউ ইয়র্কে জাতিসংঘ সাধারণ পরিষদের অধিবেশনে বৈশ্বিক তাপমাত্রা বৃদ্ধি রোধে কার্বন নির্গমন কমানোর ওপর জোর দেওয়া হয়েছে।",
        "content": (
            "নিউ ইয়র্কে জাতিসংঘের ৮০তম সাধারণ অধিবেশনে বিশ্বনেতারা জলবায়ু পরিবর্তনের মারাত্মক ঝুঁকি মোকাবিলায় একযোগে কাজ করার "
            "অঙ্গীকার ব্যক্ত করেছেন। অধিবেশনের উদ্বোধনী বক্তব্যে মহাসচিব বলেন, নবায়নযোগ্য জ্বালানি ব্যবহার বৃদ্ধি ও উন্নয়নশীল দেশগুলোকে "
            "জলবায়ু তহবিল সরবরাহ এখন সময়ের দাবি। ক্ষয়ক্ষতি কাটিয়ে উঠতে ক্ষতিগ্রস্ত দেশগুলোকে জরুরি সহায়তা প্রদানের প্রস্তাব উত্থাপিত হয়।"
        ),
        "entities": {"Person": ["মহাসচিব"], "Location": ["নিউ ইয়র্ক", "যুক্তরাষ্ট্র"], "Organization": ["জাতিসংঘ"]},
    },
]


def generate_sample_image(text_label: str = "News Image") -> bytes:
    """Generate a lightweight in-memory synthetic JPEG image."""
    img = Image.new("RGB", (400, 250), color=(30, 60, 90))
    d = ImageDraw.Draw(img)
    d.rectangle([(10, 10), (390, 240)], outline=(200, 200, 200), width=2)
    d.text((40, 110), f"WebCreoling: {text_label}", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


class MockPortalRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for Mock Bangla Newspaper Portal."""

    def log_message(self, format, *args):
        # Suppress noisy HTTP server console logs
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 1. Static Image Endpoints
        if path.startswith("/images/"):
            img_bytes = generate_sample_image(text_label=path.split("/")[-1])
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(img_bytes)))
            self.end_headers()
            self.wfile.write(img_bytes)
            return

        # 2. Category Pages with Pagination
        if path.startswith("/category/"):
            cat_name = path.replace("/category/", "").strip("/")
            page = int(query.get("page", ["1"])[0])
            matched_articles = [a for a in MOCK_ARTICLES if a["category"] == cat_name]
            if not matched_articles:
                matched_articles = MOCK_ARTICLES  # Fallback to all if unknown

            html = f"""<!DOCTYPE html>
            <html lang="bn">
            <head>
                <meta charset="UTF-8">
                <title>Mock Bangla News - {cat_name.capitalize()}</title>
            </head>
            <body>
                <h1>বিভাগ: {cat_name} (পাতা {page})</h1>
                <div class="article-list">
            """
            for art in matched_articles:
                html += f"""
                    <div class="article-card">
                        <h2 class="headline"><a class="article-card-link" href="/article/{art['id']}">{art['title']}</a></h2>
                        <p class="byline">{art['author']} | <time class="published-time">{art['published_at']}</time></p>
                        <p class="summary">{art['summary']}</p>
                    </div>
                """
            # Next page link
            if page < 3:
                html += f'<div class="pagination"><a href="/category/{cat_name}?page={page + 1}">পরবর্তী পাতা</a></div>'

            html += "</div></body></html>"
            self._send_html(html)
            return

        # 3. Individual Article Pages
        if path.startswith("/article/"):
            art_id = path.replace("/article/", "").strip("/")
            article = next((a for a in MOCK_ARTICLES if a["id"] == art_id), None)
            if not article:
                self.send_error(404, "Article Not Found")
                return

            img_url = f"http://127.0.0.1:8765/images/{article['id']}_lead.jpg"
            inline_img_url = f"http://127.0.0.1:8765/images/{article['id']}_inline.jpg"

            html = f"""<!DOCTYPE html>
            <html lang="bn">
            <head>
                <meta charset="UTF-8">
                <title>{article['title']}</title>
                <meta property="og:title" content="{article['title']}">
                <meta property="og:image" content="{img_url}">
                <meta property="article:published_time" content="{article['published_at']}">
                <meta property="article:section" content="{article['category']}">
                <meta name="author" content="{article['author']}">
                <script type="application/ld+json">
                {{
                    "@context": "https://schema.org",
                    "@type": "NewsArticle",
                    "headline": "{article['title']}",
                    "image": ["{img_url}", "{inline_img_url}"],
                    "datePublished": "{article['published_at']}",
                    "author": {{"@type": "Person", "name": "{article['author']}"}},
                    "articleBody": "{article['content']}"
                }}
                </script>
            </head>
            <body>
                <article>
                    <h1 class="article-title">{article['title']}</h1>
                    <div class="byline-section">
                        <span class="author-name">{article['author']}</span>
                        <time class="published-time">{article['published_at']}</time>
                    </div>
                    <figure>
                        <img class="featured-image" src="{img_url}" alt="{article['title']}">
                    </figure>
                    <div class="article-body">
                        <p>{article['content']}</p>
                        <p>দেশের সামগ্রিক উন্নয়ন ও অগ্রযাত্রায় এই ধরনের কার্যক্রম অত্যন্ত গুরুত্বপূর্ণ ভূমিকা পালন করে থাকে।</p>
                        <img src="{inline_img_url}" alt="Article Detail">
                    </div>
                </article>
            </body>
            </html>"""
            self._send_html(html)
            return

        # 4. Default Home Page
        html = """<!DOCTYPE html>
        <html lang="bn">
        <head><meta charset="UTF-8"><title>Mock Bangla News Portal</title></head>
        <body>
            <h1>মক বাংলা নিউজ পোর্টাল</h1>
            <ul>
                <li><a href="/category/politics">রাজনীতি (Politics)</a></li>
                <li><a href="/category/sports">খেলাধুলা (Sports)</a></li>
                <li><a href="/category/business">বাণিজ্য (Business)</a></li>
                <li><a href="/category/technology">প্রযুক্তি (Technology)</a></li>
                <li><a href="/category/international">আন্তর্জাতিক (International)</a></li>
            </ul>
        </body></html>"""
        self._send_html(html)

    def _send_html(self, html_content: str) -> None:
        data = html_content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class MockBanglaPortalServer:
    """Threaded wrapper to manage the lifecycle of the mock Bangla HTTP server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start mock server in background thread."""
        self.server = HTTPServer((self.host, self.port), MockPortalRequestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.3)  # Brief pause to ensure socket bind

    def stop(self) -> None:
        """Shutdown mock server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
