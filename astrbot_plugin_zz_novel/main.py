"""随机小说 → PDF：从轻之文库 / 文库8 抽一本书，抓若干章正文，排版成 PDF 发文件。

命令：
    小说 / 随机小说 / 来本小说 / 看小说 [源] [章节数]
        源：wenku8（默认，文库8）| linovel（linovel.net）
        章节数：1~10，默认取配置值

要点：
- 站点多为 GBK（文库8）或 SSR HTML，统一 httpx + 正则解析；
- PDF 用 reportlab 生成，内嵌微软雅黑（msyh.ttc），体积小、可选中文字；
- 章节正文过长时按配置截断，避免生成超大 PDF。
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

import astrbot.api.message_components as Comp
import httpx
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as RLImage
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
from reportlab.platypus.flowables import Flowable


class _OutlineMark(Flowable):
    """零尺寸占位：在当前位置打一个 PDF 书签（阅读器左侧目录可见）。"""

    def __init__(self, key: str, title: str, level: int = 0):
        super().__init__()
        self.key = key
        self.title = title
        self.level = level
        self.width = 0
        self.height = 0

    def draw(self):  # noqa: D102
        marker = f"{self.key}_{id(self)}"
        self.canv.bookmarkPage(marker)
        self.canv.addOutlineEntry(self.title or "章节", marker, level=self.level, closed=False)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
PROXY = "http://127.0.0.1:7890"
OUT_DIR = Path(r"D:\DSK\BOT\runtime\novel_pdf")
FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"
FONT_NAME = "MSYH"

_TAG = re.compile(r"<[^>]+>")
_LINOVEL_BOOK = re.compile(r'href="(/book/\d+\.html)"')
_LINOVEL_CHAP = re.compile(r'href="(/book/\d+/\d+\.html)"')
_LINOVEL_BODY = re.compile(r'<div[^>]+class="[^"]*article-text[^"]*"[^>]*>(.*?)</div>', re.S | re.I)
_LINOVEL_TITLE = re.compile(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', re.I)
_LINOVEL_COVER = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]*)"', re.I)
_WENKU_BOOK = re.compile(r'href="(?:https?://www\.wenku8\.net)?(/book/\d+\.htm)"')
_WENKU_CHAP = re.compile(r'href="(?:https?://www\.wenku8\.net)?(/novel/\d+/\d+/\d+\.htm)"')
_WENKU_BODY = re.compile(r'<div id="content"[^>]*>(.*?)</div>', re.S | re.I)
_WENKU_TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_PAGE_TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)


def _clean(fragment: str) -> str:
    txt = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    txt = _TAG.sub("", txt)
    txt = (
        txt.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    lines = [ln.strip() for ln in txt.split("\n")]
    return "\n".join(ln for ln in lines if ln)


@register(
    "astrbot_plugin_zz_novel",
    "yesha",
    "随机小说 → PDF（轻之文库 / 文库8）",
    "2.0.0",
    "",
)
class NovelPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self._config = config
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        self._register_font()
        self._cleanup_old_files()

    def _cleanup_old_files(self) -> None:
        """启动时清掉过期 PDF / 封面缓存（默认保留 7 天）。"""
        try:
            keep_days = max(1, min(int(self._opt("pdf_keep_days", 7)), 90))
        except Exception:
            keep_days = 7
        cutoff = time.time() - keep_days * 86400
        removed = 0
        try:
            for path in OUT_DIR.glob("*"):
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[novel] 清理旧文件失败：%r", exc)
        if removed:
            logger.info("[novel] 清理过期文件 %s 个（保留 %s 天）", removed, keep_days)

    # ---------------------------------------------------------------- 基础
    def _opt(self, key: str, default):
        cfg = self._config
        if cfg is None:
            return default
        try:
            val = cfg.get(key, default) if hasattr(cfg, "get") else getattr(cfg, key, default)
        except Exception:
            val = default
        return default if val in (None, "") else val

    @property
    def default_source(self) -> str:
        return str(self._opt("source", "wenku8")).strip().lower()

    @property
    def chapters_per_pdf(self) -> int:
        try:
            return max(1, min(int(self._opt("chapters_per_pdf", 3)), 10))
        except Exception:
            return 3

    @property
    def max_chars_per_chapter(self) -> int:
        try:
            return max(500, min(int(self._opt("max_chars_per_chapter", 6000)), 20000))
        except Exception:
            return 6000

    @staticmethod
    def _register_font() -> None:
        if FONT_NAME in pdfmetrics.getRegisteredFontNames():
            return
        try:
            pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH, subfontIndex=0))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[novel] 中文字体注册失败，回退英文排版：%r", exc)

    # ---------------------------------------------------------------- 网络
    def _client(self, timeout: float = 30.0, proxy: str | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            verify=False,
            proxy=proxy,
            trust_env=False,
        )

    async def _text(self, url: str, encoding: str | None = None, retries: int = 3) -> str:
        last: Exception | None = None
        for attempt in range(retries):
            for proxy in (None, PROXY):
                try:
                    async with self._client(proxy=proxy) as cli:
                        resp = await cli.get(url)
                    if resp.status_code == 200 and resp.content:
                        if encoding:
                            resp.encoding = encoding
                        return resp.text
                    last = RuntimeError(f"HTTP {resp.status_code}")
                except Exception as exc:  # noqa: BLE001
                    last = exc
            await asyncio.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"抓取失败 {url}：{last!r}"[:200])

    async def _download_cover(self, url: str) -> Path | None:
        if not url:
            return None
        if url.startswith("//"):
            url = "https:" + url
        for proxy in (None, PROXY):
            try:
                async with self._client(timeout=45.0, proxy=proxy) as cli:
                    resp = await cli.get(url, headers={"Referer": "https://www.wenku8.net/"})
                if resp.status_code == 200 and len(resp.content) > 1500:
                    suffix = Path(url.split("?")[0]).suffix or ".jpg"
                    if len(suffix) > 5:
                        suffix = ".jpg"
                    out = OUT_DIR / f"cover_{int(time.time() * 1000)}{suffix}"
                    out.write_bytes(resp.content)
                    return out
            except Exception:  # noqa: BLE001
                continue
        return None

    async def _bgm_cover(self, raw_title: str) -> Path | None:
        """用 Bangumi 搜同名书籍，拿高清封面（失败返回 None）。"""
        if not raw_title:
            return None
        keyword = re.split(r"[（(]", raw_title)[0].strip()
        keyword = re.sub(r"[<《》「」\s]+$", "", keyword)
        if not keyword:
            return None
        url = "https://api.bgm.tv/search/subject/" + quote(keyword) + "?type=1&responseGroup=large&max_results=5"
        headers = {"User-Agent": "yesha-astrbot-novel/2.0 (https://github.com/yesha)"}
        last: Exception | None = None
        for attempt in range(2):
            for proxy in (PROXY, None):
                try:
                    async with self._client(timeout=20.0, proxy=proxy) as cli:
                        resp = await cli.get(url, headers=headers)
                    if resp.status_code != 200:
                        last = RuntimeError(f"HTTP {resp.status_code}")
                        continue
                    data = resp.json()
                    items = data.get("list") or []
                    for item in items:
                        imgs = item.get("images") or {}
                        img_url = imgs.get("large") or imgs.get("common") or imgs.get("medium")
                        if not img_url:
                            continue
                        path = await self._download_cover(img_url)
                        if path is not None and path.stat().st_size > 8000:
                            logger.info("[novel] Bangumi 封面命中：%s", keyword)
                            return path
                except Exception as exc:  # noqa: BLE001
                    last = exc
            await asyncio.sleep(0.4)
        logger.info("[novel] Bangumi 封面未命中（%s）：%r", keyword, last)
        return None

    # ---------------------------------------------------------------- 源：轻之文库
    async def _linovel_book(self) -> dict:
        pool: list[str] = []
        for url in ("https://www.linovel.net/",):
            html = await self._text(url)
            pool.extend(_LINOVEL_BOOK.findall(html))
        pool = list(dict.fromkeys(pool))
        if not pool:
            raise RuntimeError("linovel 首页没解析出书")
        link = random.choice(pool)
        book_url = "https://www.linovel.net" + link
        html = await self._text(book_url)
        tm = _LINOVEL_TITLE.search(html) or _PAGE_TITLE.search(html)
        title = (tm.group(1) if tm else "未知书名").strip()
        title = re.sub(r"_轻小说_.*$|_轻之文库$", "", title).strip("_ ")
        am = re.search(r"由\s*([^\s，,。]{1,24}?)\s*创作", html)
        cm = _LINOVEL_COVER.search(html)
        chapters = list(dict.fromkeys(_LINOVEL_CHAP.findall(html)))
        if not chapters:
            raise RuntimeError("linovel 书页没有章节")
        return {
            "source": "轻之文库",
            "title": title,
            "author": am.group(1) if am else "未知",
            "cover": cm.group(1) if cm else "",
            "book_url": book_url,
            "chapters": [("https://www.linovel.net" + c, c) for c in chapters],
        }

    async def _linovel_chapter(self, url: str) -> tuple[str, str]:
        html = await self._text(url)
        m = _LINOVEL_BODY.search(html)
        body = _clean(m.group(1)) if m else ""
        tm = _PAGE_TITLE.search(html)
        title = re.sub(r"_轻之文库$", "", tm.group(1).strip()) if tm else "章节"
        return title.strip("_ "), body

    # ---------------------------------------------------------------- 源：文库8
    async def _wenku8_book(self) -> dict:
        # 池子顺序：本站首页可用的榜单页优先（sugoi 年度榜历年 + 年度精选），再去总点击榜
        pool: list[str] = []
        year_pages = [f"https://www.wenku8.net/zt/sugoi/{y}.php" for y in (2025, 2024, 2023, 2022)]
        for url in (
            *year_pages,
            "https://www.wenku8.net/zt/sugoi/2021.php",
            "https://www.wenku8.net/modules/article/toplist.php?sort=allvisit",
            "https://www.wenku8.net/modules/article/articlelist.php",
        ):
            try:
                html = await self._text(url, encoding="gbk")
            except Exception:  # noqa: BLE001
                continue
            pool.extend(_WENKU_BOOK.findall(html))
            if len(pool) >= 60:
                break
        pool = list(dict.fromkeys(pool))
        if not pool:
            raise RuntimeError("wenku8 列表没解析出书")
        link = random.choice(pool)
        book_url = "https://www.wenku8.net" + link
        html = await self._text(book_url, encoding="gbk")
        tm = _WENKU_TITLE.search(html)
        raw = tm.group(1).strip() if tm else "未知书名"
        title = re.split(r"\s+-\s+|_", raw)[0].strip()
        title = re.sub(r"轻小说文库|轻之文库", "", title).strip(" -_") or "未知书名"
        # 目录在 /novel/{vol}/{id}/index.htm，按卷分组
        volumes: list[dict] = []
        toc = re.search(r'href="(?:https?://www\.wenku8\.net)?(/novel/\d+/\d+/index\.htm)"', html)
        if toc:
            try:
                toc_url = "https://www.wenku8.net" + toc.group(1)
                toc_html = await self._text(toc_url, encoding="gbk")
                volumes = self._parse_wenku8_toc(toc_html, toc_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[novel] wenku8 目录解析失败：%r", exc)
        chapters = list(dict.fromkeys(_WENKU_CHAP.findall(html)))
        if not volumes and chapters:
            volumes = [{"name": "全书", "chapters": [("https://www.wenku8.net" + c, "") for c in chapters]}]
        if not volumes:
            raise RuntimeError("wenku8 书页没有章节")
        cover_url = ""
        book_id_m = re.search(r"/book/(\d+)\.htm", book_url)
        if book_id_m:
            bid = book_id_m.group(1)
            cover_m = re.search(rf'src="(http://img\.wenku8\.com/image/\d+/{bid}/{bid}s\.jpg)"', html)
            if cover_m:
                cover_url = cover_m.group(1)
        return {
            "source": "文库8",
            "title": title,
            "author": "未知",
            "cover": cover_url,
            "book_url": book_url,
            "chapters": [c for v in volumes for c in v["chapters"]],
            "volumes": volumes,
        }

    @staticmethod
    def _parse_wenku8_toc(toc_html: str, toc_url: str) -> list[dict]:
        """按 <td class=vcss>卷名</td> 把后面的章节归到该卷。"""
        base = toc_url.rsplit("/", 1)[0] + "/"
        volumes: list[dict] = []
        current = None
        for m in re.finditer(r'<td[^>]*class="vcss"[^>]*>(.*?)</td>|<a href="([^"]+\.htm)"[^>]*>(.*?)</a>', toc_html, re.S):
            if m.group(1) is not None:
                name = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                current = {"name": name or "正文", "chapters": []}
                volumes.append(current)
                continue
            href, label = m.group(2), re.sub(r"<[^>]+>", "", m.group(3)).strip()
            if "index.htm" in href or "/book/" in href:
                continue
            if current is None:
                current = {"name": "正文", "chapters": []}
                volumes.append(current)
            url = href if href.startswith("http") else base + href
            current["chapters"].append((url, label))
        return [v for v in volumes if v["chapters"]]

    async def _wenku8_chapter(self, url: str) -> tuple[str, str]:
        html = await self._text(url, encoding="gbk")
        m = _WENKU_BODY.search(html)
        body = _clean(m.group(1)) if m else ""
        tm = _PAGE_TITLE.search(html)
        title = tm.group(1).strip().split("_")[0] if tm else "章节"
        return title, body

    # ---------------------------------------------------------------- PDF 生成
    def _build_pdf(self, book: dict, chapters: list[tuple[str, str]]) -> Path:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|\s]+', "_", book["title"])[:50] or "novel"
        path = OUT_DIR / f"{safe}_{int(time.time())}.pdf"
        font = FONT_NAME if FONT_NAME in pdfmetrics.getRegisteredFontNames() else "Helvetica"
        title_style = ParagraphStyle("t", fontName=font, fontSize=20, leading=28, spaceAfter=10)
        meta_style = ParagraphStyle("m", fontName=font, fontSize=10, leading=16, spaceAfter=16, textColor="#555555")
        chap_style = ParagraphStyle("c", fontName=font, fontSize=13, leading=20, spaceBefore=8, spaceAfter=8)
        body_style = ParagraphStyle(
            "b", fontName=font, fontSize=10.5, leading=18, firstLineIndent=21, wordWrap="CJK"
        )

        doc = SimpleDocTemplate(
            str(path),
            pagesize=A5,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=16 * mm,
            bottomMargin=16 * mm,
            title=book["title"],
            author=book.get("author", ""),
        )
        story: list = [
            _OutlineMark("cover", "封面", level=0),
            Paragraph(escape(book["title"]), title_style),
            Paragraph(
                escape(f"作者：{book.get('author','未知')}　来源：{book.get('source','')}"),
                meta_style,
            ),
            Paragraph(escape(book.get("book_url", "")), meta_style),
            Paragraph(escape(book.get("volume_name") or ""), meta_style),
        ]
        cover_path = book.get("cover_path")
        if cover_path and Path(cover_path).is_file():
            try:
                from PIL import Image as PILImage

                with PILImage.open(cover_path) as im:
                    w, h = im.size
                # 封面尽量占满版心：宽最多 112mm，高最多 132mm（给标题和元信息留位）
                max_w, max_h = 112 * mm, 132 * mm
                scale = min(max_w / max(1, w), max_h / max(1, h))
                target_w, target_h = w * scale, h * scale
                story.append(Spacer(1, 10))
                story.append(RLImage(str(cover_path), width=target_w, height=target_h, hAlign="CENTER"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[novel] 封面写入失败：%r", exc)
        story += [
            PageBreak(),
        ]
        if book.get("volume_name"):
            story.append(_OutlineMark("volume", book["volume_name"], level=0))
        for idx, (chap_title, body) in enumerate(chapters, start=1):
            story.append(_OutlineMark(f"chap{idx}", chap_title or f"第{idx}章", level=1))
            story.append(Paragraph(escape(chap_title), chap_style))
            for para in body.split("\n"):
                para = para.strip()
                if not para:
                    continue
                story.append(Paragraph(escape(para), body_style))
            story.append(Spacer(1, 8))
            story.append(PageBreak())
        doc.build(story)
        return path

    # ---------------------------------------------------------------- 命令
    async def _handle(self, event: AstrMessageEvent, raw: str = ""):
        arg = str(raw or "").strip().lower()
        source = self.default_source
        count = self.chapters_per_pdf
        volume_index: int | None = None
        bare_number: int | None = None
        for token in arg.split():
            if token in ("wenku8", "文库8", "wenku"):
                source = "wenku8"
            elif token in ("linovel", "轻之文库", "linovelnet"):
                source = "linovel"
            elif m := re.fullmatch(r"第?(\d{1,3})卷?", token):
                volume_index = max(1, int(m.group(1)))
            elif m := re.fullmatch(r"(\d{1,3})章", token):
                count = max(1, min(int(m.group(1)), 10))
            elif token.isdigit():
                bare_number = max(1, min(int(token), 60))

        try:
            if source == "wenku8":
                book = await self._wenku8_book()
                fetch_chapter = self._wenku8_chapter
            else:
                book = await self._linovel_book()
                fetch_chapter = self._linovel_chapter
        except Exception as exc:  # noqa: BLE001
            logger.warning("[novel] 取书失败：%r", exc)
            yield event.plain_result("小说站点抽风了，稍后再试～")
            return

        volumes = book.get("volumes") or []
        volume_name = ""
        if volumes:
            # 有分卷：默认整卷发第一卷；命令行带 第N卷 / N 则发第 N 卷
            try:
                cap = max(1, min(int(self._opt("volume_max_chapters", 16)), 60))
            except Exception:
                cap = 16
            want = volume_index or bare_number or 1
            idx = min(max(1, want), len(volumes)) - 1
            vol = volumes[idx]
            volume_name = vol.get("name") or ""
            picked = vol["chapters"][:cap]
            count = len(picked)
        else:
            if bare_number:
                count = min(bare_number, 10)
            chaps = book["chapters"]
            start = random.randint(0, max(0, len(chaps) - count))
            picked = chaps[start : start + count]
            if len(picked) < count:  # 章节不够就补后面的，凑不齐也不强求
                picked = chaps[:count]
        rendered: list[tuple[str, str]] = []
        attempts = 0
        for url, _ in picked:
            if len(rendered) >= count or attempts >= count * 3:
                break
            attempts += 1
            try:
                ctitle, body = await fetch_chapter(url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[novel] 章节抓取失败 %s：%r", url, exc)
                continue
            if not body:
                continue
            rendered.append((ctitle, body[: self.max_chars_per_chapter]))
        if not rendered:
            yield event.plain_result("章节正文没抓到，换个源试试（小说 wenku8）")
            return

        cover_path = None
        try:
            enhance = str(self._opt("cover_enhance", "on")).strip().lower() not in ("off", "false", "0", "no")
        except Exception:
            enhance = True
        if enhance:
            cover_path = await self._bgm_cover(book.get("title") or "")
        if cover_path is None and book.get("cover"):
            cover_path = await self._download_cover(book["cover"])
        try:
            pdf = await asyncio.to_thread(
                self._build_pdf,
                {**book, "volume_name": volume_name, "cover_path": str(cover_path) if cover_path else ""},
                rendered,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[novel] PDF 生成失败：%r", exc)
            yield event.plain_result("PDF 生成失败了，看看日志～")
            return

        size_mb = pdf.stat().st_size / 1024 / 1024
        logger.info("[novel] 生成 PDF《%s》%s 章 %.1fMB", book["title"], len(rendered), size_mb)
        yield event.chain_result(
            [
                Comp.Plain(
                    f"📖《{book['title']}》 作者：{book.get('author','未知')}" + (f"　{volume_name}" if volume_name else "") + "\n"
                    f"来源：{book.get('source','')}　本次打包 {len(rendered)} 章（{size_mb:.1f}MB）\n"
                    f"{book.get('book_url','')}"
                ),
                Comp.File(name=pdf.name, file=str(pdf)),
            ]
        )

    @filter.command("小说")
    async def novel_cmd(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self._handle(event, arg):
            yield r

    @filter.command("随机小说")
    async def novel_cmd2(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self._handle(event, arg):
            yield r

    @filter.command("来本小说")
    async def novel_cmd3(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self._handle(event, arg):
            yield r

    @filter.command("看小说")
    async def novel_cmd4(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self._handle(event, arg):
            yield r

    # ---------------------------------------------------------------- 群聊免唤醒入口
    @filter.regex(r"^(小说|随机小说|来本小说|看小说)(\s+.*)?$")
    async def novel_group(self, event: AstrMessageEvent):
        """群聊直接发即可触发（RegexFilter 不受 wake_prefix 限制）。"""
        msg = (event.message_str or "").strip()
        head = msg.split()[0] if msg.split() else ""
        rest = msg[len(head):].strip()
        async for r in self.novel_cmd(event, rest):
            yield r
        event.stop_event()
