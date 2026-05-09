"""
新闻和信息获取模块
支持：网络搜索、天气查询、行业动态
"""
import os
import logging
import json
import re
import ssl
import ast
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import List, Dict

logger = logging.getLogger(__name__)


class NewsFetcher:
    """新闻和信息获取器"""

    OFFICIAL_SOURCES = [
        {
            "name": "人民网时政",
            "url": "https://www.people.com.cn/rss/politics.xml",
            "type": "rss",
            "tags": ["时政", "申论", "面试"]
        },
        {
            "name": "中国政府网最新政策",
            "url": "https://www.gov.cn/pushinfo/v150203/pushinfo.jsonp",
            "type": "jsonp",
            "tags": ["政策", "申论", "公共治理"]
        },
        {
            "name": "新华网时政",
            "url": "https://www.xinhuanet.com/politics/",
            "type": "html",
            "tags": ["时政", "社会治理", "申论"]
        },
        {
            "name": "中央机关及其直属机构考试录用公务员专题",
            "url": "http://bm.scs.gov.cn/kl2026",
            "type": "html",
            "tags": ["考公", "招录", "公告"]
        }
    ]

    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get('SEARCH_API', '')
        self.cache = {}
        self.cache_ttl = 3600  # 缓存1小时

    def _read_url(self, url, timeout=8):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 diary-web/1.0 (+personal-strategy-advisor)",
                "Accept": "text/html,application/rss+xml,application/xml,application/json;q=0.9,*/*;q=0.8"
            }
        )
        context = ssl._create_unverified_context() if url.startswith("https://") else None
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
            charset_match = re.search(r"charset=([\w-]+)", content_type, re.I)
            charset = charset_match.group(1) if charset_match else "utf-8"
            try:
                return raw.decode(charset, errors="replace"), response.geturl()
            except LookupError:
                return raw.decode("utf-8", errors="replace"), response.geturl()

    def _parse_rss_items(self, xml_text, source_name, limit=5):
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.warning("RSS解析失败 %s: %s", source_name, exc)
            return []

        items = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or item.findtext("date") or "").strip()
            description = re.sub(r"<[^>]+>", "", item.findtext("description") or "").strip()
            if title and link:
                # 解析发布时间并转换为相对时间描述
                time_desc = self._get_time_description(pub_date) if pub_date else ""
                items.append({
                    "title": unescape(title),
                    "url": link,
                    "source": source_name,
                    "published": pub_date,
                    "time_desc": time_desc,
                    "summary": unescape(description[:120])
                })
        return items

    def _is_china_media_topic(self, topic):
        topic = topic or ""
        keywords = [
            "社会热点", "热点", "时政", "政策", "民生", "治理", "就业", "教育", "医疗",
            "经济", "文化", "生态", "基层", "考公", "申论", "面试", "公务员", "公共"
        ]
        return any(keyword in topic for keyword in keywords)

    def _build_ai_web_search_prompt(self, topic, max_items=5):
        china_media_hint = ""
        suggested_query = f"{topic} 最新资讯"
        if self._is_china_media_topic(topic):
            suggested_query = f"{topic} 最新 中国媒体 人民网 新华网 央视新闻"
            china_media_hint = """
这个话题属于社会热点/公共议题，请优先搜索和引用中国媒体、官方媒体或权威中文媒体报道，例如：
人民网、新华网、央视新闻、中国政府网、中国新闻网、光明网、澎湃新闻、财新、财联社等。
"""

        return f"""请联网搜索用户日报话题的最新相关资讯，并返回适合日报展示的结果。

话题：{topic}
{china_media_hint}
搜索约束：
1. 第一次网页搜索必须围绕这个查询词：{suggested_query}
2. 搜索词必须包含原始话题「{topic}」，不得搜索与该话题无关的娱乐、晚会、B站、影视等内容，除非原始话题本身包含这些词。
3. 优先搜索过去24小时内的结果；如果不足，再放宽到过去72小时。
4. 如果第一个搜索结果偏题，请重新搜索「{topic} 最新 权威报道」。
5. 对公共议题至少再做一次媒体定向搜索，例如 site:news.cn、site:people.com.cn、site:news.cctv.com 或 site:gov.cn。

要求：
1. 必须使用网页搜索结果，不要凭空编造。
2. 优先返回最近、可信、与话题直接相关的中文资讯；同等相关时优先今天/昨天发布。
3. 返回 {max_items} 条以内。
4. 每条包含：标题、URL、来源、简短摘要。
5. 如果搜索结果不够，请如实返回已有结果。"""

    def _item_from_web_search_result(self, result, source_name="AI网页搜索"):
        if not isinstance(result, dict):
            return None
        title = (result.get("title") or result.get("name") or "").strip()
        link = (result.get("link") or result.get("url") or result.get("source_url") or "").strip()
        summary = (result.get("content") or result.get("summary") or result.get("snippet") or "").strip()
        source = (result.get("source") or result.get("site") or source_name).strip()
        published = (result.get("published") or result.get("date") or result.get("published_at") or "").strip()
        if not title or not link:
            return None
        return {
            "title": title,
            "url": link,
            "source": source,
            "published": published,
            "time_desc": self._get_time_description(published) if published else "",
            "summary": summary[:180]
        }

    def _extract_web_search_items(self, response, max_items=5):
        """Extract real search results from Anthropic-compatible web_search tool_result blocks."""
        items = []
        seen_urls = set()

        def add_item(raw, source_name="AI网页搜索"):
            item = self._item_from_web_search_result(raw, source_name)
            if not item or item["url"] in seen_urls:
                return
            seen_urls.add(item["url"])
            items.append(item)

        def parse_loose_serialized_results(content):
            """Handle provider payloads that concatenate Python/JSON-like result lists."""
            if not isinstance(content, str):
                return []

            loose_items = []
            chunks = re.findall(
                r"\{[^{}]*(?:['\"]title['\"])[^{}]*(?:(?:['\"]link['\"])|(?:['\"]url['\"]))[^{}]*\}",
                content,
                flags=re.DOTALL,
            )
            for chunk in chunks:
                try:
                    parsed = ast.literal_eval(chunk)
                except (ValueError, SyntaxError):
                    try:
                        parsed = json.loads(chunk)
                    except json.JSONDecodeError:
                        parsed = None
                if isinstance(parsed, dict):
                    loose_items.append(parsed)
                    continue

                def field(*names):
                    for name in names:
                        match = re.search(
                            rf"['\"]{re.escape(name)}['\"]\s*:\s*(['\"])(.*?)\1",
                            chunk,
                            flags=re.DOTALL,
                        )
                        if match:
                            return match.group(2).replace("\\'", "'").replace('\\"', '"').strip()
                    return ""

                raw = {
                    "title": field("title", "name"),
                    "link": field("link", "url", "source_url"),
                    "content": field("content", "summary", "snippet"),
                    "source": field("source", "site"),
                    "published": field("published", "date", "published_at"),
                }
                if raw["title"] and raw["link"]:
                    loose_items.append(raw)

            return loose_items

        def walk_payload(value):
            if isinstance(value, dict):
                add_item(value, "AI网页搜索")
                for key in ("text", "results", "items", "data", "content"):
                    if key in value:
                        walk_payload(value[key])
            elif isinstance(value, list):
                for child in value:
                    walk_payload(child)
            elif isinstance(value, str):
                for raw in parse_loose_serialized_results(value):
                    add_item(raw, "AI网页搜索")

        for block in getattr(response, "content", []) or []:
            block_type = getattr(block, "type", "")
            if block_type != "tool_result":
                continue
            content = getattr(block, "content", None)
            payload = content
            if isinstance(content, str):
                try:
                    payload = ast.literal_eval(content)
                except (ValueError, SyntaxError):
                    try:
                        payload = json.loads(content)
                    except json.JSONDecodeError:
                        payload = None

            walk_payload(payload)
            if isinstance(content, str):
                walk_payload(content)

            if len(items) >= max_items:
                break

        return items[:max_items]

    def _extract_ai_text_blocks(self, response):
        """Return assistant text blocks from a web_search response."""
        texts = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", "") == "text":
                text = getattr(block, "text", "") or ""
                if text.strip():
                    texts.append(text.strip())
        return texts

    def _extract_items_from_ai_formatted_text(self, text, max_items=5):
        """Parse the AI's formatted title/URL/source/summary output into report items."""
        if not text:
            return []

        items = []
        seen_urls = set()
        current = {}

        def clean(value):
            value = (value or "").strip()
            value = re.sub(r"^\*+|\*+$", "", value).strip()
            return value

        def commit():
            nonlocal current
            item = self._item_from_web_search_result(current, source_name="AI整理")
            if item and item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                items.append(item)
            current = {}

        label_patterns = {
            "title": r"^(?:\*\*)?标题(?:\*\*)?\s*[：:]\s*(.+)$",
            "link": r"^(?:\*\*)?(?:URL|链接|网址)(?:\*\*)?\s*[：:]\s*(https?://\S+)",
            "source": r"^(?:\*\*)?来源(?:\*\*)?\s*[：:]\s*(.+)$",
            "content": r"^(?:\*\*)?(?:摘要|简述|内容)(?:\*\*)?\s*[：:]\s*(.+)$",
        }

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            link_match = re.search(r"\[([^\]]+)\]\((https?://[^)]+)\)", line)
            if link_match:
                if current.get("title") and current.get("link"):
                    commit()
                current["title"] = clean(link_match.group(1))
                current["link"] = clean(link_match.group(2))
                continue

            matched = False
            for field, pattern in label_patterns.items():
                match = re.search(pattern, line, flags=re.IGNORECASE)
                if not match:
                    continue
                if field == "title" and current.get("title") and current.get("link"):
                    commit()
                current[field] = clean(match.group(1))
                matched = True
                break
            if matched:
                continue

            plain_url = re.search(r"(https?://\S+)", line)
            if plain_url and current.get("title") and not current.get("link"):
                current["link"] = plain_url.group(1).rstrip("。；;，,")

        if current.get("title") and current.get("link"):
            commit()

        return items[:max_items]

    def _item_age_hours(self, item):
        published = (item.get("published") or "").strip() if isinstance(item, dict) else ""
        if not published:
            return None
        try:
            dt = parsedate_to_datetime(published)
        except (TypeError, ValueError, IndexError):
            try:
                dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600)

    def _select_best_topic_items(self, topic, items, max_items=5):
        """Prefer concrete reports over portal homepages, encyclopedias, and Q&A pages."""
        topic = topic or ""
        preferred_domains = (
            "people.com.cn", "news.cn", "xinhuanet.com", "cctv.com", "chinanews.com.cn",
            "gov.cn", "gmw.cn", "thepaper.cn", "caixin.com", "cls.cn"
        )
        blocked_domains = ("wikipedia.org", "zhihu.com", "youtube.com", "bilibili.com")

        def score(item):
            title = item.get("title", "")
            summary = item.get("summary", "")
            url = item.get("url", "")
            parsed = urllib.parse.urlparse(url)
            domain = parsed.netloc.lower()
            path = parsed.path or "/"
            text = f"{title} {summary}"

            value = 0
            if any(domain.endswith(d) for d in preferred_domains):
                value += 30
            if any(domain.endswith(d) for d in blocked_domains):
                value -= 80
            if path in ("", "/"):
                value -= 35
            if re.search(r"\.(s?html?|cms)$", path, flags=re.IGNORECASE):
                value += 15
            if "首页" in title or "网上的人民日报" in title or "让新闻离你更近" in title:
                value -= 25
            if topic and topic in text:
                value += 25
            age_hours = self._item_age_hours(item)
            if age_hours is not None:
                if age_hours <= 24:
                    value += 30
                elif age_hours <= 72:
                    value += 15
                elif age_hours > 24 * 7:
                    value -= 15
            for keyword in ("社会", "民生", "治理", "政策", "法治", "热点", "最新", "报道"):
                if keyword in text:
                    value += 4
            return value

        ranked = sorted(items or [], key=score, reverse=True)
        cleaner_ranked = [item for item in ranked if not self._is_low_value_topic_item(item)]
        pool = cleaner_ranked or ranked

        selected = []
        seen_urls = set()
        for item in pool:
            url = item.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            selected.append(item)
            if len(selected) >= max_items:
                break
        return selected

    def _is_low_value_topic_item(self, item):
        """Detect pages that are usually poor daily-report sources."""
        url = item.get("url", "") if isinstance(item, dict) else ""
        title = item.get("title", "") if isinstance(item, dict) else ""
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path or "/"

        if any(blocked in domain for blocked in ("wikipedia.org", "zhihu.com", "youtube.com", "bilibili.com")):
            return True
        if path in ("", "/"):
            return True
        low_value_title_parts = (
            "首页", "网上的人民日报", "让新闻离你更近", "世界就在眼前",
            "中华人民共和国媒体", "新闻频道_央视网", "滚动新闻", "频道_"
        )
        return any(part in title for part in low_value_title_parts)

    def _augment_with_china_media_news(self, topic, items, max_candidates=12):
        """Add targeted Chinese media search candidates for broad public topics."""
        if not self._is_china_media_topic(topic):
            return items or []

        queries = [
            f'{topic} site:people.com.cn/society',
            f'{topic} site:news.cn',
            f'{topic} site:news.cctv.com',
            f'{topic} site:chinanews.com.cn',
            f'{topic} 民生 治理 最新报道',
        ]
        merged = list(items or [])
        seen_urls = {item.get("url") for item in merged if item.get("url")}

        for query in queries:
            result = self.fetch_web_news_items(query, max_items=4)
            for item in result.get("items", []):
                url = item.get("url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                merged.append(item)
                if len(merged) >= max_candidates:
                    return merged
        return merged

    def _format_web_search_items_with_ai(self, topic, items, ai_engine=None, max_items=5):
        """Let the built-in AI select and normalize raw web_search candidates."""
        if not items or not ai_engine or not getattr(ai_engine, "is_available", lambda: False)():
            return []

        candidate_payload = []
        cleaned_items = [
            item for item in self._select_best_topic_items(topic, items, max_items=15)
            if not self._is_low_value_topic_item(item)
        ]
        if not cleaned_items:
            cleaned_items = self._select_best_topic_items(topic, items, max_items=15)

        for item in cleaned_items[:15]:
            candidate_payload.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "source": item.get("source", ""),
                "summary": item.get("summary", ""),
                "published": item.get("published", ""),
            })

        prompt = f"""请从下面这些网页搜索候选结果中，筛选并整理用户日报话题的资讯。

话题：{topic}

候选结果：
{json.dumps(candidate_payload, ensure_ascii=False, indent=2)}

要求：
1. 只能使用候选结果中的 URL，不要新增或编造 URL。
2. 优先选择与话题直接相关的具体新闻/报道/政策页面。
3. 尽量排除门户首页、百科、问答站、视频频道首页、搜索结果页。
4. 社会热点优先选择人民网、新华网、央视新闻、中国新闻网、中国政府网等中国媒体报道。
5. 返回 JSON 数组，不要解释。每个对象字段为 title、url、source、summary、published。
6. 最多返回 {max_items} 条。"""

        try:
            response = ai_engine.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=900,
                messages=[{"role": "user", "content": prompt}]
            )
            text = "\n\n".join(self._extract_ai_text_blocks(response))
            match = re.search(r"\[[\s\S]*\]", text)
            if not match:
                return []
            parsed = json.loads(match.group(0))
        except Exception as exc:
            logger.warning("AI资讯格式化失败 %s: %s", topic, exc)
            return []

        formatted = []
        allowed_urls = {item.get("url") for item in candidate_payload if item.get("url")}
        for raw in parsed if isinstance(parsed, list) else []:
            item = self._item_from_web_search_result(raw, source_name="AI整理")
            if item and item["url"] in allowed_urls and not self._is_low_value_topic_item(item):
                formatted.append(item)
            if len(formatted) >= max_items:
                break
        return formatted

    def fetch_ai_web_search_topic_news(self, topic, ai_engine=None, max_items=5) -> Dict:
        """Use the configured AI API's web_search tool to fetch real topic news."""
        display_topic = (topic or "").replace("custom:", "").strip()
        if not display_topic or not ai_engine or not getattr(ai_engine, "is_available", lambda: False)():
            return {
                "type": "topic_news",
                "title": f"{display_topic or '话题'}｜相关资讯",
                "content": "AI 网页搜索暂不可用，已切换到备用资讯源。",
                "source": "AI网页搜索（不可用）",
                "timestamp": datetime.now().isoformat(),
                "items": []
            }

        prompt = self._build_ai_web_search_prompt(display_topic, max_items=max_items)
        try:
            response = ai_engine.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1600,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
                messages=[{"role": "user", "content": prompt}]
            )
            ai_text = "\n\n".join(self._extract_ai_text_blocks(response))
            formatted_items = self._extract_items_from_ai_formatted_text(ai_text, max_items=max_items)
            raw_candidates = self._extract_web_search_items(response, max_items=max(max_items * 6, 15))
            raw_candidates = self._augment_with_china_media_news(
                display_topic,
                raw_candidates,
                max_candidates=max(max_items * 8, 18)
            )
            ai_selected_items = []
            if not formatted_items:
                ai_selected_items = self._format_web_search_items_with_ai(
                    display_topic,
                    raw_candidates,
                    ai_engine=ai_engine,
                    max_items=max_items
                )
            items = (
                formatted_items
                or ai_selected_items
                or self._select_best_topic_items(display_topic, raw_candidates, max_items=max_items)
            )
        except Exception as exc:
            logger.warning("AI网页搜索失败 %s: %s", display_topic, exc)
            items = []

        if not items:
            return {
                "type": "topic_news",
                "title": f"{display_topic}｜相关资讯",
                "content": "AI 网页搜索没有返回可解析的结果，已切换到备用资讯源。",
                "source": "AI网页搜索（无结果）",
                "timestamp": datetime.now().isoformat(),
                "items": []
            }

        now = datetime.now()
        lines = [f"> ⏰ 更新时间：{now.strftime('%Y年%m月%d日 %H:%M')}"]
        media_hint = "中国媒体优先" if self._is_china_media_topic(display_topic) else "全网中文资讯"
        lines.append(f"> 🔎 搜索方式：AI API 网页搜索（{media_hint}）\n")

        for idx, item in enumerate(items, start=1):
            time_info = item.get("time_desc") or item.get("published", "")
            if time_info:
                time_info = f"｜{time_info}"
            lines.append(f"{idx}. [{item['title']}]({item['url']})")
            lines.append(f"   来源：{item['source']}{time_info}")
            if item.get("summary"):
                lines.append(f"   摘要：{item['summary']}")

        return {
            "type": "topic_news",
            "title": f"{display_topic}｜相关资讯",
            "content": "\n".join(lines),
            "source": "AI API 网页搜索",
            "timestamp": datetime.now().isoformat(),
            "items": items
        }

    def _build_topic_search_queries(self, topic, ai_engine=None, limit=3):
        """Use the configured AI engine to turn a topic into concrete news searches."""
        topic = (topic or "").replace("custom:", "").strip()
        if not topic:
            return []

        fallback = [
            f"{topic} 最新消息",
            f"{topic} 政策 新闻",
            f"{topic} 深度解读"
        ]

        if not ai_engine or not getattr(ai_engine, "is_available", lambda: False)():
            return fallback[:limit]

        prompt = f"""请把用户订阅的日报话题改写成适合中文新闻搜索的查询词。

话题：{topic}

要求：
1. 返回 {limit} 个搜索查询词，每行一个。
2. 查询词要具体，优先包含“最新”“政策”“新闻”“解读”等资讯意图。
3. 不要编号，不要解释。"""

        try:
            response = ai_engine.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=120,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text
            queries = []
            for line in text.splitlines():
                query = re.sub(r"^[\-\d\.\、\s]+", "", line).strip()
                if query and query not in queries:
                    queries.append(query)
                if len(queries) >= limit:
                    break
            return queries or fallback[:limit]
        except Exception as exc:
            logger.warning("AI生成新闻搜索词失败，使用降级搜索词: %s", exc)
            return fallback[:limit]

    def _get_time_description(self, pub_date_str):
        """将发布时间转换为相对时间描述"""
        if not pub_date_str:
            return ""

        pub_dt = None
        raw = str(pub_date_str).strip()

        try:
            pub_dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            pass

        if pub_dt is None:
            formats = [
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d"
            ]
            for fmt in formats:
                try:
                    pub_dt = datetime.strptime(raw, fmt)
                    if fmt.endswith("Z"):
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue

        if pub_dt is None:
            return ""

        now = datetime.now(pub_dt.tzinfo) if pub_dt.tzinfo else datetime.now()
        diff = now - pub_dt
        seconds = diff.total_seconds()
        if seconds < -300:
            return "刚刚"

        hours = max(0, seconds) / 3600
        if hours < 1:
            return "刚刚"
        if hours < 24:
            return f"{int(hours)}小时前"
        if hours < 48:
            return "昨天"
        if hours < 72:
            return "前天"

        days = int(hours / 24)
        return f"{days}天前"

    def _parse_html_links(self, html_text, base_url, source_name, limit=5):
        html_text = re.sub(r"\s+", " ", html_text)
        candidates = []
        for href, text in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html_text, re.I):
            title = re.sub(r"<[^>]+>", "", text)
            title = unescape(title).strip()
            if len(title) < 8 or len(title) > 80:
                continue
            if any(skip in title for skip in ["首页", "更多", "客户端", "微博", "微信", "English", "ICP备", "公网安备", "网站无障碍"]):
                continue
            if any(skip in href for skip in ["beian", "javascript:", "mailto:"]):
                continue
            link = urllib.parse.urljoin(base_url, href)
            if not link.startswith("http"):
                continue
            candidates.append({
                "title": title,
                "url": link,
                "source": source_name,
                "published": "",
                "summary": ""
            })

        seen = set()
        items = []
        for item in candidates:
            key = (item["title"], item["url"])
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
            if len(items) >= limit:
                break
        return items

    def _parse_bing_search_results(self, html_text, source_name="Bing网页搜索", limit=5):
        """Parse regular Bing result HTML as a fallback when RSS is unavailable."""
        html_text = re.sub(r"\s+", " ", html_text)
        blocks = re.findall(r'<li[^>]+class=["\'][^"\']*b_algo[^"\']*["\'][^>]*>(.*?)</li>', html_text, re.I)
        if not blocks:
            blocks = re.findall(r'<h2[^>]*>.*?</h2>(?:\s*<div[^>]*>.*?</div>)?', html_text, re.I)

        candidates = []
        for block in blocks:
            match = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', block, re.I)
            if not match:
                continue
            href, text = match.groups()
            title = re.sub(r"<[^>]+>", "", text)
            title = unescape(title).strip()
            if len(title) < 6 or len(title) > 120:
                continue

            link = unescape(href).strip()
            if link.startswith("/"):
                link = urllib.parse.urljoin("https://www.bing.com", link)
            if not link.startswith("http") or "bing.com/search" in link:
                continue

            summary = ""
            summary_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.I)
            if summary_match:
                summary = re.sub(r"<[^>]+>", "", summary_match.group(1))
                summary = unescape(summary).strip()[:160]

            candidates.append({
                "title": title,
                "url": link,
                "source": source_name,
                "published": "",
                "time_desc": "",
                "summary": summary
            })

        seen = set()
        items = []
        for item in candidates:
            key = item["url"]
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
            if len(items) >= limit:
                break
        return items

    def _parse_jsonp_items(self, text, source_name, limit=5):
        match = re.search(r"\(([\s\S]*)\)\s*;?\s*$", text.strip())
        if not match:
            return []
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            logger.warning("JSONP解析失败 %s: %s", source_name, exc)
            return []

        items = []
        for item in payload[:limit]:
            title = (item.get("title") or item.get("description") or "").strip()
            link = (item.get("link") or item.get("url") or "").strip()
            if not title or not link:
                continue
            items.append({
                "title": unescape(title),
                "url": link,
                "source": source_name,
                "published": item.get("pubDate", ""),
                "time_desc": self._get_time_description(item.get("pubDate", "")),
                "summary": unescape((item.get("description") or "")[:120])
            })
        return items

    def fetch_official_items(self, query="考公", per_source=4, max_items=12) -> Dict:
        """从内置官方源获取真实文章链接。"""
        normalized_query = (query or "").replace("custom:", "").strip()
        query_terms = [term for term in re.split(r"[、,，\s]+", normalized_query) if term]
        if not query_terms:
            query_terms = ["考公", "申论", "面试", "政策"]

        all_items = []
        failures = []
        for source in self.OFFICIAL_SOURCES:
            try:
                text, final_url = self._read_url(source["url"])
                if source["type"] == "rss":
                    items = self._parse_rss_items(text, source["name"], per_source)
                elif source["type"] == "jsonp":
                    items = self._parse_jsonp_items(text, source["name"], per_source)
                else:
                    items = self._parse_html_links(text, final_url, source["name"], per_source)
                all_items.extend(items)
            except Exception as exc:
                logger.warning("官方源获取失败 %s: %s", source["name"], exc)
                failures.append(f"{source['name']}暂时不可用")

        if not all_items:
            return {
                "type": "official_news",
                "title": "今日官方资讯",
                "content": "官方资讯源暂时没有抓取到内容，请稍后重试。\n\n" + "\n".join(f"- {item}" for item in failures),
                "source": "；".join(source["name"] for source in self.OFFICIAL_SOURCES),
                "timestamp": datetime.now().isoformat()
            }

        scored = []
        for item in all_items:
            haystack = item["title"] + " " + item.get("summary", "")
            score = sum(2 for term in query_terms if term and term in haystack)
            if any(term in haystack for term in ["政策", "治理", "服务", "基层", "就业", "教育", "科技", "公务员", "考试", "招录"]):
                score += 1
            scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)

        chosen = []
        seen_urls = set()
        for _, item in scored:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            chosen.append(item)
            if len(chosen) >= max_items:
                break

        lines = []
        now = datetime.now()
        lines.append(f"> ⏰ 更新时间：{now.strftime('%Y年%m月%d日 %H:%M')}\n")

        for idx, item in enumerate(chosen, start=1):
            # 优先显示相对时间，如果没有则显示原始时间
            time_info = item.get('time_desc') or item.get('published', '')
            if time_info:
                time_info = f"｜{time_info}"

            lines.append(f"{idx}. [{item['title']}]({item['url']})")
            lines.append(f"   来源：{item['source']}{time_info}")
            angle = self._material_angle(item["title"])
            if angle:
                lines.append(f"   申论/面试角度：{angle}")
            if item.get("summary"):
                lines.append(f"   摘要：{item['summary']}")

        if failures:
            lines.append("\n抓取提示：" + "；".join(failures))

        return {
            "type": "official_news",
            "title": "今日官方资讯与申论素材",
            "content": "\n".join(lines),
            "source": "；".join(sorted({item["source"] for item in chosen})),
            "timestamp": datetime.now().isoformat(),
            "items": chosen
        }

    def fetch_web_news_items(self, query, max_items=5) -> Dict:
        """Search the web news feed for a user-selected topic."""
        topic = (query or "").replace("custom:", "").strip()
        if not topic:
            return {
                "type": "topic_news",
                "title": "话题资讯",
                "content": "话题为空，无法搜索相关资讯。",
                "source": "日报系统",
                "timestamp": datetime.now().isoformat(),
                "items": []
            }

        search_url = (
            "https://www.bing.com/news/search?"
            + urllib.parse.urlencode({"q": topic, "format": "rss", "mkt": "zh-CN"})
        )
        failures = []
        items = []
        try:
            xml_text, _ = self._read_url(search_url, timeout=8)
            items = self._parse_rss_items(xml_text, "Bing新闻搜索", limit=max_items * 2)
        except Exception as exc:
            logger.warning("联网搜索资讯失败 %s: %s", topic, exc)
            failures.append("Bing新闻搜索暂时不可用")

        if not items:
            try:
                html_url = (
                    "https://www.bing.com/search?"
                    + urllib.parse.urlencode({"q": f"{topic} 新闻 最新", "mkt": "zh-CN"})
                )
                html_text, _ = self._read_url(html_url, timeout=8)
                items = self._parse_bing_search_results(html_text, "Bing网页搜索", limit=max_items * 2)
            except Exception as exc:
                logger.warning("联网网页搜索失败 %s: %s", topic, exc)
                failures.append("Bing网页搜索暂时不可用")

        chosen = []
        seen_urls = set()
        for item in items:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            chosen.append(item)
            if len(chosen) >= max_items:
                break

        if not chosen:
            fallback = self.fetch_official_items(topic, per_source=3, max_items=max_items)
            fallback["type"] = "topic_news"
            fallback["title"] = f"{topic}｜相关资讯"
            if failures:
                fallback["content"] += "\n\n> 联网搜索提示：" + "；".join(failures)
            return fallback

        now = datetime.now()
        lines = [f"> ⏰ 更新时间：{now.strftime('%Y年%m月%d日 %H:%M')}"]
        lines.append(f"> 🔎 搜索话题：{topic}\n")

        for idx, item in enumerate(chosen, start=1):
            time_info = item.get("time_desc") or item.get("published", "")
            if time_info:
                time_info = f"｜{time_info}"
            lines.append(f"{idx}. [{item['title']}]({item['url']})")
            lines.append(f"   来源：{item['source']}{time_info}")
            if item.get("summary"):
                lines.append(f"   摘要：{item['summary']}")

        return {
            "type": "topic_news",
            "title": f"{topic}｜相关资讯",
            "content": "\n".join(lines),
            "source": "；".join(sorted({item["source"] for item in chosen})),
            "timestamp": datetime.now().isoformat(),
            "items": chosen
        }

    def fetch_ai_guided_topic_news(self, topic, ai_engine=None, max_items=5) -> Dict:
        """Use AI-generated search queries, then fetch real web news results."""
        display_topic = (topic or "").replace("custom:", "").strip()

        ai_search_result = self.fetch_ai_web_search_topic_news(display_topic, ai_engine=ai_engine, max_items=max_items)
        if ai_search_result.get("items"):
            return ai_search_result

        queries = self._build_topic_search_queries(display_topic, ai_engine=ai_engine, limit=3)

        all_items = []
        seen_urls = set()
        sources = set()
        for query in queries:
            result = self.fetch_web_news_items(query, max_items=max_items)
            sources.add(result.get("source", ""))
            for item in result.get("items", []):
                if item["url"] in seen_urls:
                    continue
                seen_urls.add(item["url"])
                all_items.append(item)
                if len(all_items) >= max_items:
                    break
            if len(all_items) >= max_items:
                break

        if not all_items:
            return self.fetch_web_news_items(display_topic, max_items=max_items)

        now = datetime.now()
        lines = [f"> ⏰ 更新时间：{now.strftime('%Y年%m月%d日 %H:%M')}"]
        lines.append(f"> 🔎 AI搜索词：{'；'.join(queries)}\n")

        for idx, item in enumerate(all_items, start=1):
            time_info = item.get("time_desc") or item.get("published", "")
            if time_info:
                time_info = f"｜{time_info}"
            lines.append(f"{idx}. [{item['title']}]({item['url']})")
            lines.append(f"   来源：{item['source']}{time_info}")
            if item.get("summary"):
                lines.append(f"   摘要：{item['summary']}")

        return {
            "type": "topic_news",
            "title": f"{display_topic}｜相关资讯",
            "content": "\n".join(lines),
            "source": "；".join(sorted(source for source in sources if source)) or "联网搜索",
            "timestamp": datetime.now().isoformat(),
            "items": all_items,
            "queries": queries
        }

    def _material_angle(self, title):
        rules = [
            ("基层", "基层治理、群众路线、最后一公里"),
            ("服务", "公共服务、便民效率、政策落地"),
            ("就业", "民生保障、青年发展、稳就业"),
            ("教育", "公平发展、公共资源配置"),
            ("科技", "科技创新、新质生产力、治理现代化"),
            ("政策", "政策执行、监督评估、系统观念"),
            ("公务员", "职业选择、公共责任、依法行政"),
            ("招录", "考公信息、岗位选择、备考节奏")
        ]
        for keyword, angle in rules:
            if keyword in title:
                return angle
        return "可按问题-原因-对策-评估四步转成申论素材"

    def fetch_weather(self, location="北京"):
        """获取天气信息（简化版）"""
        # 实际项目中可调用天气API
        now = datetime.now()
        date_str = now.strftime("%Y年%m月%d日")
        weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
        time_str = now.strftime("%H:%M")

        return {
            "type": "weather",
            "title": f"{date_str} {weekday}",
            "content": f"> ⏰ 当前时间：{time_str}\n\n📍 {location}\n今日天气晴朗，气温适宜。\n\n提醒：注意补充水分，适当运动。",
            "source": "天气服务",
            "timestamp": datetime.now().isoformat()
        }

    def fetch_industry_news(self, topics: List[str]) -> List[Dict]:
        """获取行业动态

        Args:
            topics: 话题列表，如 ["嵌入式", "AI", "半导体"]
        """
        results = []

        # 简化版：返回通用建议
        # 实际项目可调用新闻API或使用Web搜索
        for topic in topics[:3]:
            results.append({
                "type": "industry_news",
                "title": f"{topic}行业动态",
                "content": f"关于{topic}的最新发展：\n"
                          f"- 关注技术趋势和标准更新\n"
                          f"- 学习最佳实践和案例\n"
                          f"- 参与社区讨论和交流",
                "source": "行业追踪",
                "timestamp": datetime.now().isoformat()
            })

        return results

    def fetch_aihot_items(self, take=8) -> Dict:
        """获取 AI 热点条目，带链接，失败时自动降级。"""
        url = f"https://aihot.virxact.com/api/public/items?mode=selected&take={int(take)}"
        now = datetime.now()

        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "diary-web/1.0 (+personal-strategy-advisor)",
                    "Accept": "application/json"
                }
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("获取 AI 热点失败: %s", exc)
            return {
                "type": "aihot",
                "title": "AI热点与工具动态",
                "content": f"> ⏰ 更新时间：{now.strftime('%Y年%m月%d日 %H:%M')}\n\nAI热点接口暂时不可用，今天先关注：工具是否能提高复盘效率、是否能沉淀申论素材、是否值得加入日常流程。",
                "source": "AI热点接口（暂不可用）",
                "timestamp": datetime.now().isoformat()
            }

        items = payload.get("items") or payload.get("data") or []
        if isinstance(items, dict):
            items = items.get("items") or []
        lines = []
        lines.append(f"> ⏰ 更新时间：{now.strftime('%Y年%m月%d日 %H:%M')}\n")

        for item in items[:take]:
            title = item.get("title") or item.get("name") or "未命名条目"
            link = item.get("url") or item.get("link") or item.get("source_url") or ""
            source = item.get("source") or item.get("site") or "AI热点"

            # 尝试获取发布时间
            time_info = ""
            if item.get("published_at") or item.get("date") or item.get("created_at"):
                pub_str = item.get("published_at") or item.get("date") or item.get("created_at")
                time_desc = self._get_time_description(pub_str)
                if time_desc:
                    time_info = f"｜{time_desc}"

            if link:
                lines.append(f"- [{title}]({link}) - {source}{time_info}")
            else:
                lines.append(f"- {title} - {source}{time_info}")

        return {
            "type": "aihot",
            "title": "AI热点与工具动态",
            "content": "\n".join(lines) if lines else "今天暂无可用热点条目。",
            "source": "https://aihot.virxact.com/api/public/items",
            "timestamp": datetime.now().isoformat()
        }

    def fetch_shenlun_materials(self) -> Dict:
        """申论素材默认积累，每天轮换不同主题。"""
        import random

        now = datetime.now()
        day_of_month = now.day
        date_str = now.strftime("%Y年%m月%d日")

        themes = [
            {
                "title": "社会治理专题",
                "content": """- 基层治理要看见真实问题，材料可从"群众诉求、部门协同、数字治理、最后一公里"四个角度积累。
- 公共服务：评价一项政策，不只看口号，要看覆盖人群、办理成本、反馈机制和长期维护。
- 今日练习：看到一条新闻时，补齐"问题是什么、原因是什么、谁负责、怎么改、如何评估"五句话。"""
            },
            {
                "title": "青年成长专题",
                "content": """- 把个人奋斗放进公共需要里，表达时少喊口号，多讲事实、责任和可执行行动。
- 职业选择：基层不是"退而求其次"，是了解国情、服务群众的最好课堂。
- 今日练习：用"问题-原因-对策-效果"四步法分析一个你关心的社会现象。"""
            },
            {
                "title": "经济发展专题",
                "content": """- 新质生产力：技术创新不是炫技，要解决实际问题、提升生产效率。
- 民营经济：看企业贡献不看规模大小，看就业吸纳、税收贡献、社会价值。
- 今日练习：找一个你所在行业的案例，分析它如何通过技术创新提升效率。"""
            },
            {
                "title": "生态文明专题",
                "content": """- 绿色发展：环保不是发展对立面，是高质量发展的内在要求。
- 双碳目标：碳达峰、碳中和是硬约束，也是产业升级的机会窗口。
- 今日练习：观察身边的环境变化，用"现状-问题-建议"三段式写一段短评。"""
            },
            {
                "title": "文化自信专题",
                "content": """- 传统文化：不是简单复古，要创造性转化、创新性发展。
- 舆论引导：网络空间也是公共空间，发言要有事实依据、理性表达。
- 今日练习：选择一个你熟悉的传统文化元素，思考它如何在现代社会焕发新活力。"""
            }
        ]

        # 根据日期选择主题，确保每天不同
        theme = themes[day_of_month % len(themes)]

        return {
            "type": "shenlun",
            "title": f"申论素材与面试表达 - {theme['title']}",
            "content": f"> 📅 {date_str} 专属素材\n\n{theme['content']}",
            "source": "内置申论素材框架",
            "timestamp": datetime.now().isoformat()
        }

    def fetch_learning_tips(self) -> Dict:
        """获取学习建议"""
        tips = [
            "番茄工作法：专注25分钟，休息5分钟",
            "主动回忆：合上书本，尝试复述所学内容",
            "间隔重复：1天后、3天后、7天后复习",
            "费曼技巧：用简单语言解释复杂概念",
            "项目驱动：通过实际项目巩固知识"
        ]

        import random
        tip = random.choice(tips)

        return {
            "type": "learning_tip",
            "title": "今日学习建议",
            "content": tip,
            "source": "学习方法库",
            "timestamp": datetime.now().isoformat()
        }

    def fetch_health_reminder(self) -> Dict:
        """获取健康提醒，每天不同主题"""
        import random

        now = datetime.now()
        day_of_month = now.day
        date_str = now.strftime("%Y年%m月%d日")

        health_themes = [
            {
                "title": "睡眠健康日",
                "content": """💤 今日睡眠主题
• 保证7-8小时睡眠，比补觉更重要
• 睡前1小时远离电子屏幕
• 固定作息时间，周末也尽量保持
• 午休20-30分钟最佳，不超过1小时"""
            },
            {
                "title": "饮食健康日",
                "content": """🥗 今日饮食主题
• 规律三餐，不吃过饱
• 每天至少5种蔬果
• 少糖少盐，多喝水
• 细嚼慢咽，每口嚼20次以上"""
            },
            {
                "title": "运动健康日",
                "content": """🏃 今日运动主题
• 每天至少30分钟中等强度运动
• 久坐1小时起身活动5分钟
• 找个喜欢的运动，坚持比强度重要
• 运动后拉伸，预防肌肉僵硬"""
            },
            {
                "title": "护眼健康日",
                "content": """👀 今日护眼主题
• 用眼40分钟，远眺5分钟
• 屏幕亮度与环境光匹配
• 多眨眼，保持眼球湿润
• 每天户外活动1小时以上"""
            },
            {
                "title": "心理健康日",
                "content": """🧠 今日心理主题
• 接纳情绪，负面情绪也正常
• 每天记录3件值得感谢的事
• 深呼吸：4秒吸7秒憋8秒呼
• 需要时寻求帮助，求助不是软弱"""
            }
        ]

        theme = health_themes[day_of_month % len(health_themes)]

        return {
            "type": "health_reminder",
            "title": f"健康生活提醒 - {theme['title']}",
            "content": f"> 📅 {date_str} 健康主题\n\n{theme['content']}",
            "source": "健康指南",
            "timestamp": datetime.now().isoformat()
        }

    def fetch_reading_recommendation(self) -> Dict:
        """获取阅读推荐"""
        books = [
            {"title": "深度工作", "author": "Cal Newport", "reason": "提升专注力和工作质量"},
            {"title": "认知觉醒", "author": "周岭", "reason": "理解大脑运作，提升学习效率"},
            {"title": "原则", "author": "Ray Dalio", "reason": "建立个人决策框架"},
            {"title": "思考，快与慢", "author": "Daniel Kahneman", "reason": "理解思维模式"}
        ]

        import random
        book = random.choice(books)

        return {
            "type": "reading",
            "title": "今日推荐阅读",
            "content": f"📖 《{book['title']}》\n"
                      f"作者：{book['author']}\n"
                      f"推荐理由：{book['reason']}",
            "source": "书库",
            "timestamp": datetime.now().isoformat()
        }

    def cross_validate(self, information: str, sources: List[str] = None) -> Dict:
        """交叉验证信息准确性

        Args:
            information: 需要验证的信息
            sources: 可选的来源列表
        """
        # 简化版：返回验证结果
        # 实际项目可调用多个数据源进行交叉验证
        return {
            "validated": True,
            "confidence": "medium",
            "sources_checked": sources or ["内部知识库"],
            "note": "信息基于通用知识，建议核实具体细节"
        }


class DailyReportGenerator:
    """日报生成器"""

    def __init__(self, db, ai_engine, news_fetcher=None):
        self.db = db
        self.ai_engine = ai_engine
        self.news_fetcher = news_fetcher or NewsFetcher()

    def generate(self, user_id, topics=None):
        """生成日报

        Args:
            user_id: 用户ID
            topics: 自定义话题列表，为None则使用默认话题
        """
        from models import DailyReport, ReportConfig, Diary

        # 获取用户配置
        config = ReportConfig.query.filter_by(user_id=user_id).first()
        if config and not config.enabled:
            return {"error": "日报推送已禁用"}

        # 确定使用的话题
        if topics:
            use_topics = topics
        elif config and config.get_topics():
            use_topics = config.get_topics()
        else:
            use_topics = self._default_topics()
        use_topics = self._normalize_topics(use_topics)

        # 收集信息
        sections = []
        section_keys = set()
        sources = []
        historical_item_keys = self._recent_report_item_keys(user_id)
        run_item_keys = set()

        for topic in use_topics:
            section = self._generate_section(topic, user_id)
            if section:
                section = self._filter_section_items(section, historical_item_keys, run_item_keys)
                section_key = self._section_key(section)
                if section_key in section_keys:
                    continue
                section_keys.add(section_key)
                sections.append(section)
                if section.get("source"):
                    sources.append({
                        "title": section.get("title", ""),
                        "source": section.get("source", ""),
                        "items": section.get("items", [])
                    })

        # 获取今日日记（如果有）
        today = datetime.now().strftime("%Y-%m-%d")
        today_diary = Diary.query.filter_by(
            user_id=user_id,
            date=today
        ).first()

        diary_summary = ""
        if today_diary:
            # 保留更多日记内容，避免截断过早
            content = today_diary.content
            if len(content) > 3000:
                content = content[:3000] + "\n\n...(内容较长，已截断，完整内容请查看今日日记)"
            diary_summary = f"\n\n## 今日记录摘要\n{content}"

        # 生成完整报告
        now = datetime.now()
        date_str = now.strftime('%Y年%m月%d日')
        time_str = now.strftime('%H:%M')
        weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]

        report_content = f"# 每日日报\n\n"
        report_content += f"📅 **{date_str} {weekday} {time_str}**\n\n"
        report_content += f"> ⏰ 本日报生成于 {time_str}，资讯内容实时抓取，请关注时效性\n\n"

        for section in sections:
            report_content += f"## {section['title']}\n\n"
            report_content += f"{section['content']}\n\n"

        report_content += diary_summary

        # 生成简短摘要
        summary = f"今日共{len(sections)}个话题，" \
                  f"{'已记录今日日记' if today_diary else '尚未记录今日日记'}。"

        # 保存报告
        report = DailyReport(
            user_id=user_id,
            report_date=today,
            content=report_content,
            summary=summary
        )
        report.set_diary_ids([today_diary.id] if today_diary else [])
        report.set_sources(sources)

        self.db.session.add(report)
        self.db.session.commit()

        return {
            "report": report_content,
            "summary": summary,
            "sections": len(sections),
            "has_diary": bool(today_diary),
            "report_id": report.id
        }

    def _generate_section(self, topic, user_id):
        """根据话题生成内容"""
        # 保留原始 topic 用于显示标题
        original_topic = topic or ""
        topic = topic.replace("custom:", "").strip()
        topic_lower = topic.lower()

        # 官方资讯：按用户选择的话题联网搜索，不把不同话题混成同一个资讯池
        if any(key in topic for key in ["官方", "资讯", "时政", "政策", "考公", "申论", "面试", "素材", "新闻"]):
            result = self.news_fetcher.fetch_ai_guided_topic_news(topic, ai_engine=self.ai_engine, max_items=5)
            # 确保标题包含原始话题名称
            if original_topic.startswith("custom:"):
                result["title"] = topic
            return result

        # 天气与提醒
        if "天气" in topic or "提醒" in topic:
            return self.news_fetcher.fetch_weather()

        # AI热点
        if "ai" in topic_lower or "热点" in topic or "工具" in topic:
            result = self.news_fetcher.fetch_aihot_items(take=8)
            if original_topic.startswith("custom:"):
                result["title"] = topic
            return result

        # 行业动态也按选中话题联网搜索，返回真实链接
        if "行业" in topic or "动态" in topic or "新闻" in topic:
            result = self.news_fetcher.fetch_ai_guided_topic_news(topic, ai_engine=self.ai_engine, max_items=5)
            if original_topic.startswith("custom:"):
                result["title"] = topic
            return result

        # 个人成长
        if "成长" in topic or "建议" in topic:
            return self.news_fetcher.fetch_learning_tips()

        # 健康生活
        if "健康" in topic:
            return self.news_fetcher.fetch_health_reminder()

        # 阅读推荐
        if "阅读" in topic or "推荐" in topic:
            return self.news_fetcher.fetch_reading_recommendation()

        # 自定义话题：尝试从官方源获取相关内容
        if original_topic.startswith("custom:"):
            result = self.news_fetcher.fetch_ai_guided_topic_news(topic, ai_engine=self.ai_engine, max_items=5)
            result["title"] = topic
            return result

        # 默认返回通用内容
        return {
            "type": "general",
            "title": topic,
            "content": f"## {topic}\n\n关于「{topic}」的相关内容正在收集中。您可以尝试调整话题名称，使其更具体，例如：\n- 加上「行业」关键词可获取行业动态\n- 加上「政策」关键词可获取政策资讯\n- 或在配置中取消此话题，选择其他预设话题",
            "source": "日报系统",
            "timestamp": datetime.now().isoformat()
        }

    def _item_key(self, item):
        if not isinstance(item, dict):
            return ""
        url = (item.get("url") or "").strip()
        if url:
            parsed = urllib.parse.urlparse(url)
            clean_query = urllib.parse.urlencode([
                (k, v) for k, v in urllib.parse.parse_qsl(parsed.query)
                if not k.lower().startswith("utm_") and k.lower() not in {"spm", "from"}
            ])
            return urllib.parse.urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip('/'), '', clean_query, ''))
        title = re.sub(r'\s+', '', item.get("title", ""))
        return title[:80]

    def _recent_report_item_keys(self, user_id, days=3):
        if not self.db:
            return set()
        from models import DailyReport
        reports = DailyReport.query.filter_by(user_id=user_id)\
            .order_by(DailyReport.report_date.desc(), DailyReport.created_at.desc()).limit(days).all()
        keys = set()
        for report in reports:
            for source in report.get_sources():
                if isinstance(source, dict):
                    for item in source.get("items", []) or []:
                        key = self._item_key(item)
                        if key:
                            keys.add(key)
            for title, url in re.findall(r'\[([^\]]+)\]\((https?://[^)]+)\)', report.content or ''):
                key = self._item_key({"title": title, "url": url})
                if key:
                    keys.add(key)
        return keys

    def _rebuild_items_content(self, section, removed_count=0):
        items = section.get("items") or []
        if not items:
            if removed_count:
                section["content"] = f"> 已过滤 {removed_count} 条最近日报出现过的重复资讯，暂未找到足够新的独立条目。"
            return section

        now = datetime.now()
        lines = [f"> ⏰ 更新时间：{now.strftime('%Y年%m月%d日 %H:%M')}"]
        if removed_count:
            lines.append(f"> 已自动过滤 {removed_count} 条最近日报重复资讯")
        lines.append("")
        for idx, item in enumerate(items, start=1):
            time_info = item.get("time_desc") or item.get("published", "")
            if time_info:
                time_info = f"｜{time_info}"
            lines.append(f"{idx}. [{item['title']}]({item['url']})")
            lines.append(f"   来源：{item.get('source', '未知')}{time_info}")
            if item.get("summary"):
                lines.append(f"   摘要：{item['summary']}")
        section["content"] = "\n".join(lines)
        return section

    def _filter_section_items(self, section, historical_keys, run_keys):
        items = section.get("items")
        if not items:
            return section
        kept = []
        removed = 0
        for item in items:
            key = self._item_key(item)
            if key and (key in historical_keys or key in run_keys):
                removed += 1
                continue
            if key:
                run_keys.add(key)
            kept.append(item)
        if removed:
            section = dict(section)
            section["items"] = kept
            return self._rebuild_items_content(section, removed_count=removed)
        return section

    def _normalize_topics(self, topics):
        """清理完全重复的话题，保留用户选中的不同话题。"""
        normalized = []
        seen = set()

        for raw_topic in topics or []:
            if not raw_topic:
                continue
            topic = str(raw_topic).strip()
            if not topic:
                continue
            key = topic.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(topic)

        return normalized

    def _section_key(self, section):
        """生成板块去重键，防止同一信息源被多个话题重复展开。"""
        if section.get("type") == "official_news":
            return ("official_news", section.get("title") or "官方资讯")
        if section.get("type") == "topic_news":
            return ("topic_news", section.get("title") or "话题资讯")
        return (section.get("type") or "", section.get("title") or "")

    def _default_topics(self):
        """默认话题列表"""
        return [
            "官方时政与政策资讯",
            "考公申论素材与面试表达",
            "AI热点与工具动态",
            "今日天气与提醒",
            "个人成长建议",
            "健康生活提示"
        ]


# 全局实例
news_fetcher = NewsFetcher()
report_generator = None


def init_report_generator(db, ai_engine):
    """初始化报告生成器"""
    global report_generator
    report_generator = DailyReportGenerator(db, ai_engine, news_fetcher)
    return report_generator
