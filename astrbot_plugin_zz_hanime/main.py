"""里番：hanime1.me 随机 / 最新上市 / 新番预告。

输出统一为「聊天记录（两层）」：内层每条一部番（标题+日期+链接+封面），外层套标题 + 嵌套卡片。
支持每日新作推送、每周日全群预告推送。

命令：
    里番 [N] / 随机里番 [N]      首页随机抽 N 部（默认 1，最多 5）
    里番新作 [N]                 最新上市前 N 部（默认 5，最多 10）
    里番预告 [N] / 新番预告 [N]   新番预告前 N 部（默认 8，最多 20，带发售日）
    里番 搜索 关键词              关键词搜索
"""

from __future__ import annotations

import asyncio
import base64
import os
import json
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import astrbot.api.message_components as Comp
import httpx
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain

HOST = "https://hanime1.me"
PREVIEW_URL = HOST + "/search?genre=%E6%96%B0%E7%95%AA%E9%A0%90%E5%91%8A"
NEW_URL = HOST + "/search?sort=%E6%9C%80%E6%96%B0%E4%B8%8A%E5%B8%82"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
PROXY = "http://127.0.0.1:7890"
FFMPEG_BIN = r"D:\DSK\BOT\_tools\ffmpeg\ffmpeg.exe"
CACHE = Path(r"D:\DSK\BOT\runtime\hanime_cache")
OWNER_UMO = "aiocqhttp:FriendMessage:2899675402"
NAPCAT_WS = "ws://127.0.0.1:3001"
NAPCAT_TOKEN = "napcat_ws_1132046"
GENRES = {
    "里番": "裏番",
    "裏番": "裏番",
    "泡面番": "泡麵番",
    "泡麵番": "泡麵番",
    "motion": "Motion Anime",
    "motion anime": "Motion Anime",
    "3dcg": "3DCG",
    "2.5d": "2.5D動畫",
    "2d": "2D動畫",
    "2d动画": "2D動畫",
    "ai": "AI生成",
    "ai生成": "AI生成",
    "mmd": "MMD",
    "cosplay": "Cosplay",
}
RANKS = {"今日": "本日排行", "本周": "本週排行", "本月": "本月排行"}
BOT_UID = 1132046
BOT_NICK = "鲸鱼娘"

_CARD = re.compile(
    r'<div title="(?P<title>[^"]*)" class="video-item-container">.*?'
    r'<a href="(?P<link>https://hanime1\.me/watch\?v=\d+)".*?'
    r'<img class="main-thumb" src="(?P<img>[^"]+)".*?'
    r'<div class="duration">\s*(?P<dur>[\d:]+)\s*</div>',
    re.S,
)
_WATCH = re.compile(r'href="(https://hanime1\.me/watch\?v=\d+)"')
_TITLE = re.compile(r'<div class="home-rows-videos-title">\s*([^<]*?)\s*</div>')
_IMG = re.compile(r'<img[^>]+src="([^"]+)"')
_DATE = re.compile(r'<div class="hidden-xs"[^>]*>\s*([^<]{2,20}?)\s*</div>')


@register(
    "astrbot_plugin_zz_hanime",
    "yesha",
    "里番：hanime1.me 随机/新作/预告（两层聊天记录 + 自动推送）",
    "2.1.0",
    "",
)
class HanimePlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self._config = config
        self._task: asyncio.Task | None = None
        self._weekly_task: asyncio.Task | None = None
        CACHE.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- 配置
    def _opt(self, key: str, default):
        cfg = self._config
        if cfg is None:
            return default
        try:
            val = cfg.get(key, default) if hasattr(cfg, "get") else getattr(cfg, key, default)
        except Exception:
            val = default
        return default if val in (None, "") else val

    # ---------------------------------------------------------------- 抓取
    async def _html(self, url: str) -> str:
        last: Exception | None = None
        for attempt in range(2):
            for proxy in (PROXY, None):
                try:
                    async with httpx.AsyncClient(
                        timeout=25,
                        verify=False,
                        proxy=proxy,
                        trust_env=False,
                        follow_redirects=True,
                        headers={"User-Agent": UA, "Referer": HOST + "/"},
                    ) as cli:
                        resp = await cli.get(url)
                    if resp.status_code == 200 and resp.text:
                        return resp.text
                    last = RuntimeError(f"HTTP {resp.status_code}")
                except Exception as exc:  # noqa: BLE001
                    last = exc
            await asyncio.sleep(0.6 * (attempt + 1))
        raise RuntimeError(f"抓取失败 {url}：{last!r}"[:200])

    def _parse_cards(self, html: str) -> list[dict]:
        items: list[dict] = []
        seen: set[str] = set()
        for m in _CARD.finditer(html):
            link = m.group("link")
            if link in seen:
                continue
            seen.add(link)
            items.append(
                {
                    "title": m.group("title").strip(),
                    "link": link,
                    "img": m.group("img").replace("&amp;", "&"),
                    "dur": m.group("dur"),
                }
            )
        return items

    def _parse_grid(self, html: str) -> list[dict]:
        items: list[dict] = []
        seen: set[str] = set()
        for m in _WATCH.finditer(html):
            link = m.group(1)
            if link in seen:
                continue
            seen.add(link)
            chunk = html[m.start() : m.start() + 2200]
            tm = _TITLE.search(chunk)
            title = (tm.group(1) if tm else "").strip()
            if not title:
                continue
            im = _IMG.search(chunk)
            dm = _DATE.search(chunk)
            items.append(
                {
                    "title": title,
                    "link": link,
                    "img": (im.group(1) if im else "").replace("&amp;", "&"),
                    "dur": (dm.group(1) if dm else "").strip(),
                }
            )
        return items

    async def _items(self, url: str) -> list[dict]:
        html = await self._html(url)
        return self._parse_cards(html) or self._parse_grid(html)

    def _genre_url(self, genre: str, sort: str = "最新上傳") -> str:
        from urllib.parse import quote

        return HOST + "/search?genre=" + quote(genre, safe="") + ("&sort=" + quote(sort, safe="") if sort else "")

    async def _items_genre(self, genre: str, sort: str = "最新上傳") -> list[dict]:
        html = await self._html(self._genre_url(genre, sort))
        # 分类页两种结构都可能：先按首页卡片解析，再退回网格结构
        return self._parse_cards(html) or self._parse_grid(html)

    async def _items_rank(self, sort: str, genre: str = "") -> list[dict]:
        from urllib.parse import quote

        url = HOST + "/search?sort=" + quote(sort, safe="")
        if genre:
            url += "&genre=" + quote(genre, safe="")
        html = await self._html(url)
        return self._parse_cards(html) or self._parse_grid(html)

    async def _pool_from_genres(self, genres: list[str], per: int = 30) -> list[dict]:
        """并发拉多个分类，合并成随机池。"""
        tasks = [self._items_genre(g, "最新上傳") for g in genres]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        pool: list[dict] = []
        seen: set[str] = set()
        for res in results:
            if isinstance(res, Exception):
                continue
            for it in res[:per]:
                if it["link"] in seen:
                    continue
                seen.add(it["link"])
                pool.append(it)
        return pool

    async def _items_preview(self) -> list[dict]:
        return self._parse_grid(await self._html(PREVIEW_URL))

    @staticmethod
    def _shrink(raw: bytes, width: int = 200, quality: int = 72) -> str:
        """压缩成小 JPEG 再 base64：聊天记录载荷要小，否则群转发报 1200/ECONNRESET。"""
        try:
            import io

            from PIL import Image

            im = Image.open(io.BytesIO(raw)).convert("RGB")
            w, h = im.size
            im = im.resize((width, max(1, int(h * width / w))), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=quality, optimize=True)
            return base64.b64encode(buf.getvalue()).decode()
        except Exception:  # noqa: BLE001
            return ""

    async def _cover_b64(self, url: str, width: int = 360) -> str:
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        for proxy in (PROXY, None):
            try:
                async with httpx.AsyncClient(
                    timeout=25,
                    verify=False,
                    proxy=proxy,
                    trust_env=False,
                    follow_redirects=True,
                    headers={"User-Agent": UA, "Referer": HOST + "/"},
                ) as cli:
                    resp = await cli.get(url)
                if resp.status_code == 200 and len(resp.content) > 2048:
                    small = self._shrink(resp.content, width)
                    if small:
                        return small
                    return base64.b64encode(resp.content).decode()
            except Exception:  # noqa: BLE001
                continue
        return ""

    async def _video_frame(self, watch_url: str, out: Path, at: int = 5) -> bool:
        """用 ffmpeg 从 720p 源视频抽一帧（真·视频原图），失败返回 False。"""
        if not watch_url or not os.path.exists(FFMPEG_BIN):
            return False
        try:
            html = await self._html(watch_url)
        except Exception:  # noqa: BLE001
            return False
        m = re.search(r'https://vdownload\.hembed\.com/\d+-720p\.mp4\?secure=[^"\' ]+', html)
        if not m:
            m = re.search(r'https://vdownload\.hembed\.com/\d+-\d+p\.mp4\?secure=[^"\' ]+', html)
        if not m:
            return False
        mp4 = m.group(0)
        try:
            proc = await asyncio.create_subprocess_exec(
                FFMPEG_BIN, "-hide_banner", "-loglevel", "error",
                "-http_proxy", PROXY, "-ss", str(at), "-i", mp4,
                "-frames:v", "1", "-q:v", "3", str(out), "-y",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=90)
        except Exception:  # noqa: BLE001
            return False
        return out.exists() and out.stat().st_size > 8192

    async def _cover_raw(self, url: str) -> bytes | None:
        """抓封面原图（不缩放、不压质量）。"""
        if not url:
            return None
        if url.startswith("//"):
            url = "https:" + url
        for proxy in (PROXY, None):
            try:
                async with httpx.AsyncClient(
                    timeout=30, verify=False, proxy=proxy, trust_env=False, follow_redirects=True,
                    headers={"User-Agent": UA, "Referer": HOST + "/"},
                ) as cli:
                    resp = await cli.get(url)
                if resp.status_code == 200 and len(resp.content) > 2048:
                    return resp.content
            except Exception:  # noqa: BLE001
                continue
        return None

    # ---------------------------------------------------------------- OneBot 通道
    async def _ws(self):
        import websockets

        ws_url = str(self._opt("napcat_ws", NAPCAT_WS))
        token = str(self._opt("napcat_token", NAPCAT_TOKEN))
        return await websockets.connect(
            ws_url,
            additional_headers={"Authorization": f"Bearer {token}"},
            max_size=32 * 1024 * 1024,
        )

    async def _call(self, ws, action: str, params: dict, echo: str) -> dict:
        await ws.send(json.dumps({"action": action, "params": params, "echo": echo}, ensure_ascii=False))
        while True:
            data = json.loads(await asyncio.wait_for(ws.recv(), timeout=180))
            if data.get("echo") == echo:
                return data

    async def _action(self, action: str, params: dict) -> dict:
        """优先用 AstrBot 已连接的 aiocqhttp 客户端，失败再直连 NapCat WS。"""
        try:
            platform = self.context.get_platform("aiocqhttp")
            bot = getattr(platform, "bot", None) if platform is not None else None
            if bot is not None:
                res = await bot.call_action(action, **params)
                if isinstance(res, dict):
                    if "status" in res or "retcode" in res:
                        return res
                    return {"status": "ok", "data": res}
                return {"status": "ok", "data": res if res is not None else {}}
        except Exception as exc:  # noqa: BLE001
            logger.info("[hanime] AstrBot 客户端 %s 失败：%r", action, exc)
        try:
            async with await self._ws() as ws:
                return await self._call(ws, action, params, f"a{int(time.time() * 1000) % 100000}")
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "message": repr(exc)[:100]}

    # ---------------------------------------------------------------- 聊天记录
    async def _prepare_cover_files(self, items: list[dict], width: int = 0) -> list[Path | None]:
        """封面优先级：视频原帧(720p) → og:image 高清图 → 列表缩略图。"""
        CACHE.mkdir(parents=True, exist_ok=True)
        out: list[Path | None] = []
        for idx, it in enumerate(items, 1):
            watch = str(it.get("link") or it.get("url") or "").strip()
            tag = f"cv_{abs(hash((watch, it.get('img', ''), idx)))}"
            frame = CACHE / f"{tag}_frame.jpg"
            if frame.exists() and frame.stat().st_size > 8192:
                out.append(frame)
                continue
            got = False
            if watch:
                for at in (5, 2, 12):
                    if await self._video_frame(watch, frame, at):
                        got = True
                        break
            if not got:
                # 退而求其次：从视频页拿 og:image（通常是 1024x576 h 图）
                og = ""
                if watch:
                    try:
                        html = await self._html(watch)
                        mm = re.search(r'property="og:image" content="([^"]+)"', html)
                        if mm:
                            og = mm.group(1)
                    except Exception:  # noqa: BLE001
                        og = ""
                raw = None
                for u in (og, str(it.get("img") or "")):
                    if not u:
                        continue
                    for _ in range(3):
                        raw = await self._cover_raw(u)
                        if raw:
                            break
                        await asyncio.sleep(1.0)
                    if raw:
                        break
                if raw:
                    ext = ".png" if raw[:8].startswith(b"\x89PNG") else ".jpg"
                    frame = CACHE / f"{tag}{ext}"
                    frame.write_bytes(raw)
                    got = True
            out.append(frame if got else None)
            await asyncio.sleep(0.3)
        return out

    async def _inner_nodes(self, items: list[dict], with_cover: bool = True, width: int = 360) -> list[dict]:
        files = await self._prepare_cover_files(items, width) if with_cover else [None] * len(items)
        nodes: list[dict] = []
        for idx, it in enumerate(items, 1):
            date = f"｜{it.get('dur')}" if it.get("dur") else ""
            content: list[dict] = [
                {"type": "text", "data": {"text": f"{idx}. {it['title']}{date}\n{it['link']}"}}
            ]
            f = files[idx - 1] if idx - 1 < len(files) else None
            if f is not None:
                content.append({"type": "image", "data": {"file": f"file:///{f}"}})
            nodes.append({"type": "node", "data": {"user_id": BOT_UID, "nickname": BOT_NICK, "content": content}})
        return nodes

    async def _collage(self, items: list[dict], cols: int = 5, cell: int = 190) -> Path | None:
        """把封面拼成一张图（一路正常图片消息发出去，比塞进聊天记录稳得多）。"""
        try:
            import io

            from PIL import Image

            covers: list[bytes] = []
            for it in items:
                b64 = await self._cover_b64(it.get("img", ""))
                if b64:
                    covers.append(base64.b64decode(b64))
            if not covers:
                return None
            imgs = []
            for raw in covers:
                im = Image.open(io.BytesIO(raw)).convert("RGB")
                w, h = im.size
                im = im.resize((cell, max(1, int(h * cell / w))), Image.LANCZOS)
                imgs.append(im)
            rows = (len(imgs) + cols - 1) // cols
            cell_h = max(i.height for i in imgs)
            canvas = Image.new("RGB", (cols * cell, rows * cell_h), (24, 22, 20))
            for idx, im in enumerate(imgs):
                x = (idx % cols) * cell
                y = (idx // cols) * cell_h
                canvas.paste(im, (x, y))
            out = CACHE / f"collage_{int(time.time() * 1000)}.jpg"
            canvas.save(out, "JPEG", quality=82, optimize=True)
            return out
        except Exception as exc:  # noqa: BLE001
            logger.info("[hanime] 拼图失败：%r", exc)
            return None

    async def _send_covers(self, items: list[dict], private_id: int | None = None, group_id: int | None = None, limit: int = 6) -> int:
        """逐张发封面（普通图片消息，比塞进合并转发稳）。返回成功张数。"""
        action = "send_private_msg" if private_id else "send_group_msg"
        target = {"user_id": private_id} if private_id else {"group_id": group_id}
        sent = 0
        for it in items[:limit]:
            b64 = await self._cover_b64(it.get("img", ""))
            if not b64:
                continue
            res = await self._action(action, {**target, "message": [{"type": "image", "data": {"file": "base64://" + b64}}]})
            if res.get("status") == "ok":
                sent += 1
            else:
                logger.info("[hanime] 封面发送失败：%s", str(res.get("message") or "")[:50])
            await asyncio.sleep(0.7)
        return sent

    async def _send_collage(self, items: list[dict], private_id: int | None = None, group_id: int | None = None) -> bool:
        path = await self._collage(items)
        if path is None:
            return False
        action = "send_private_msg" if private_id else "send_group_msg"
        target = {"user_id": private_id} if private_id else {"group_id": group_id}
        res = await self._action(
            action,
            {**target, "message": [{"type": "image", "data": {"file": f"file:///{str(path)}"}}]},
        )
        if res.get("status") != "ok":
            logger.info("[hanime] 拼图发送失败：%s", str(res.get("message") or "")[:60])
            return False
        return True

    async def _send_forward(
        self,
        items: list[dict],
        header: str,
        private_id: int | None = None,
        group_id: int | None = None,
        with_cover: bool = False,
    ) -> tuple[bool, str]:
        """两层：内层（每部一个 node，默认纯文字更稳）→ 外层（抬头 + 文本+嵌套卡片）。"""
        if not items:
            return False, "空内容"
        action = "send_private_forward_msg" if private_id else "send_group_forward_msg"
        target = {"user_id": private_id} if private_id else {"group_id": group_id}

        async def send(nodes: list[dict]) -> str:
            res = await self._action(action, {**target, "messages": nodes})
            if res.get("status") == "ok":
                data = res.get("data") or {}
                return str(data.get("message_id") or data.get("messageId") or "ok")
            logger.info("[hanime] 转发失败：%s", str(res.get("message") or res.get("wording") or "")[:80])
            return ""

        head = {
            "type": "node",
            "data": {
                "user_id": BOT_UID,
                "nickname": BOT_NICK,
                "content": [{"type": "text", "data": {"text": header}}],
            },
        }
        ok_any = False
        # 单层聊天记录：抬头 + 每部一条（带封面优先，逐级降级）
        # 只允许「带图」发送：缩图 → 再缩 → 拆成两段各带图，永远不退纯文字
        widths = [0, 480, 320, 240]
        if not with_cover:
            widths = []
        for width in widths:
            nodes = [head] + await self._inner_nodes(items, True, width)
            if await send(nodes):
                return True, f"with-cover@{width}"
            await asyncio.sleep(2.5)
        if with_cover and len(items) > 1:
            mid = (len(items) + 1) // 2
            parts = [(items[:mid], "上半"), (items[mid:], "下半")]
            done = 0
            for part, label in parts:
                if not part:
                    continue
                sent_part = False
                for width in (0, 480, 320, 240):
                    for attempt in range(3):
                        nodes = [head] + await self._inner_nodes(part, True, width)
                        if await send(nodes):
                            sent_part = True
                            logger.info("[hanime] 分段发送 %s(%s) %s 部 → %spx 成功", label, "1/2" if done == 0 else "2/2", len(part), width)
                            break
                        await asyncio.sleep(3.0)
                    if sent_part:
                        break
                if sent_part:
                    done += 1
                else:
                    logger.warning("[hanime] 分段发送失败：%s（%s 部）", label, len(part))
                await asyncio.sleep(3.0)
            if done:
                return True, f"with-cover-split({done}/2)"
        if not with_cover:
            nodes = [head] + await self._inner_nodes(items, False)
            if await send(nodes):
                return True, "text-only"
        return False, "发送失败"

    async def _send_blocks(
        self,
        header: str,
        blocks: list[dict],
        private_id: int | None = None,
        group_id: int | None = None,
    ) -> bool:
        """blocks: [{"text": "...", "img": "url"}] → 一层聊天记录（抬头 + 每块一个 node，可带封面）。"""
        if not blocks:
            return False
        action = "send_private_forward_msg" if private_id else "send_group_forward_msg"
        target = {"user_id": private_id} if private_id else {"group_id": group_id}
        head = {
            "type": "node",
            "data": {"user_id": BOT_UID, "nickname": BOT_NICK, "content": [{"type": "text", "data": {"text": header}}]},
        }
        nodes = [head]
        for blk in blocks:
            content: list[dict] = [{"type": "text", "data": {"text": blk["text"]}}]
            if blk.get("img"):
                b64 = await self._cover_b64(blk["img"], 300)
                if b64:
                    content.append({"type": "image", "data": {"file": "base64://" + b64}})
            nodes.append(
                {"type": "node", "data": {"user_id": BOT_UID, "nickname": BOT_NICK, "content": content}}
            )
        for _ in range(2):
            res = await self._action(action, {**target, "messages": nodes})
            if res.get("status") == "ok":
                return True
            logger.info("[hanime] 聊天记录发送失败：%s", str(res.get("message") or "")[:70])
            await asyncio.sleep(2.5)
        return False

    async def _chain(self, header: str, items: list[dict], with_cover: bool = True) -> MessageChain:
        chain: list = [Comp.Plain(header)]
        for idx, it in enumerate(items, 1):
            date = f"｜{it.get('dur')}" if it.get("dur") else ""
            chain.append(Comp.Plain(f"\n{idx}. {it['title']}{date}\n{it['link']}"))
            if with_cover:
                b64 = await self._cover_b64(it.get("img", ""))
                if b64:
                    CACHE.mkdir(parents=True, exist_ok=True)
                    path = CACHE / f"c_{idx}_{int(time.time() * 1000)}.jpg"
                    path.write_bytes(base64.b64decode(b64))
                    chain.append(Comp.Image(file=str(path)))
        return MessageChain(chain)

    # ---------------------------------------------------------------- 会话工具
    @staticmethod
    def _event_uid(event) -> int | None:
        try:
            if "FriendMessage" in str(getattr(event, "unified_msg_origin", "")):
                return int(event.get_sender_id())
        except Exception:  # noqa: BLE001
            pass
        return None

    @staticmethod
    def _event_gid(event) -> int | None:
        try:
            if "GroupMessage" in str(getattr(event, "unified_msg_origin", "")):
                return int(event.get_group_id())
        except Exception:  # noqa: BLE001
            pass
        return None

    async def _deliver(self, event, items: list[dict], header: str):
        """聊天记录（合并转发），每部一个节点、节点内 文字+封面图。"""
        uid = self._event_uid(event)
        gid = self._event_gid(event)
        ok, how = await self._send_forward(items, header, private_id=uid, group_id=gid, with_cover=True)
        logger.info("[hanime] 输出 %s：%s(%s)", "私聊" if uid else f"群{gid}", ok, how)
        if ok:
            return None
        blocks = [{"text": f"{i}. {it['title']}" + (f"｜{it['dur']}" if it.get("dur") else "") + f"\n{it['link']}", "img": it.get("img", "")} for i, it in enumerate(items, 1)]
        if await self._send_blocks(header, blocks, private_id=uid, group_id=gid):
            return None
        return await self._chain(header, items)

    async def _download_links(self, watch_url: str) -> dict[str, str]:
        """从 /download?v=ID 页解析各画质直链（vdownload.hembed.com/ID-1080p.mp4?secure=...）。"""
        m = re.search(r"[?&]v=(\d+)", watch_url or "")
        if not m:
            return {}
        html = await self._html(HOST + "/download?v=" + m.group(1))
        links: dict[str, str] = {}
        for url in re.findall(r"https?://[^\"'<> ]+\.mp4[^\"'<> ]*", html):
            q = re.search(r"-(\d+p)\.mp4", url)
            if q:
                links.setdefault(q.group(1), url.replace("&amp;", "&"))
        return links

    # ---------------------------------------------------------------- 命令
    @filter.command("里番")
    async def hanime_cmd(self, event: AstrMessageEvent, arg: str = ""):
        arg = str(arg or "").strip()
        if arg.startswith("搜索") or arg.startswith("搜"):
            kw = arg[2:].strip() if arg.startswith("搜索") else arg[1:].strip()
            if not kw:
                yield event.plain_result("搜什么？例如：里番 搜索 催眠")
                return
            try:
                items = await self._items(HOST + "/search?query=" + httpx.QueryParams({"query": kw})["query"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("[hanime] 搜索失败：%r", exc)
                yield event.plain_result("搜不到，稍后再试～")
                return
            if not items:
                yield event.plain_result(f"没搜到「{kw}」")
                return
            chain = await self._deliver(event, items[:5], f"🔍 搜索「{kw}」（共 {len(items)} 条）")
            if chain is not None:
                yield event.chain_result(chain)
            return

        # 解析：可选分类 + 数量，例如「里番 3」「里番 3DCG 2」
        n = 1
        genre_key = ""
        for token in arg.split():
            low = token.lower()
            if token.isdigit():
                n = max(1, min(int(token), 5))
            elif low in GENRES:
                genre_key = GENRES[low]
        if genre_key:
            genres = [genre_key]
            label = f"{genre_key}"
        else:
            all_genres = list(dict.fromkeys(GENRES.values()))
            genres = random.sample(all_genres, 3)
            label = " / ".join(genres)
        try:
            pool = await self._pool_from_genres(genres)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[hanime] 分类池抓取失败：%r", exc)
            pool = []
        if not pool:
            try:
                pool = [it for it in await self._items(HOST + "/") if it.get("title")]
                label = "首页"
            except Exception as exc:  # noqa: BLE001
                logger.warning("[hanime] 首页兜底也失败：%r", exc)
                yield event.plain_result("站点打不开（需要代理），稍后再试～")
                return
        if not pool:
            yield event.plain_result("没抓到内容～")
            return
        picked = random.sample(pool, min(n, len(pool)))
        chain = await self._deliver(event, picked, f"🔞 随机里番 · {label}（{len(pool)} 部里抽 {len(picked)} 部）")
        if chain is not None:
            yield event.chain_result(chain)

    @filter.command("随机里番")
    async def random_cmd(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self.hanime_cmd(event, arg):
            yield r

    @filter.command("里番新作")
    async def new_cmd(self, event: AstrMessageEvent, arg: str = ""):
        n = 5
        if str(arg).strip().isdigit():
            n = max(1, min(int(str(arg).strip()), 20))
        try:
            items = [it for it in await self._items(NEW_URL) if it.get("title")]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[hanime] 新作抓取失败：%r", exc)
            yield event.plain_result("站点打不开，稍后再试～")
            return
        picked = items[:n]
        chain = await self._deliver(event, picked, f"🆕 最新上市（共 {len(items)} 部，取前 {len(picked)} 部）")
        if chain is not None:
            yield event.chain_result(chain)

    @filter.command("里番预告")
    async def preview_cmd(self, event: AstrMessageEvent, arg: str = ""):
        n = 8
        if str(arg).strip().isdigit():
            n = max(1, min(int(str(arg).strip()), 20))
        try:
            items = await self._items_preview()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[hanime] 预告抓取失败：%r", exc)
            yield event.plain_result("预告页打不开，稍后再试～")
            return
        if not items:
            yield event.plain_result("没抓到预告～")
            return
        picked = items[:n]
        chain = await self._deliver(event, picked, f"📅 里番新番预告（共 {len(items)} 部，取前 {len(picked)} 部）")
        if chain is not None:
            yield event.chain_result(chain)

    @filter.command("新番预告")
    async def preview_cmd2(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self.preview_cmd(event, arg):
            yield r

    @filter.command("里番下载")
    async def download_cmd(self, event: AstrMessageEvent, arg: str = ""):
        """随机抽 1~3 部，直接给 mp4 直链（1080p 优先）。"""
        n = 1
        genre_key = ""
        for token in str(arg or "").split():
            low = token.lower()
            if token.isdigit():
                n = max(1, min(int(token), 3))
            elif low in GENRES:
                genre_key = GENRES[low]
        genres = [genre_key] if genre_key else random.sample(list(dict.fromkeys(GENRES.values())), 2)
        try:
            pool = await self._pool_from_genres(genres)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[hanime] 下载池抓取失败：%r", exc)
            pool = []
        if not pool:
            yield event.plain_result("没抓到内容，稍后再试～")
            return
        picked = random.sample(pool, min(n, len(pool)))
        blocks: list[dict] = []
        for idx, it in enumerate(picked, 1):
            try:
                links = await self._download_links(it["link"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("[hanime] 直链解析失败 %s：%r", it["link"], exc)
                links = {}
            best = links.get("1080p") or links.get("720p") or links.get("480p") or ""
            dur = f"｜{it['dur']}" if it.get("dur") else ""
            text = f"{idx}. {it['title']}{dur}"
            text += f"\n🔗 {best}" if best else "\n🔗 没有解析到（可能被限流）"
            blocks.append({"text": text, "img": it.get("img", "")})
            await asyncio.sleep(0.5)
        header = f"⬇️ 里番直链（{' / '.join(genres)} · {len(blocks)} 部）"
        ok = await self._send_blocks(
            header, blocks, private_id=self._event_uid(event), group_id=self._event_gid(event)
        )
        if not ok:
            yield event.plain_result("\n".join([header] + [b["text"] for b in blocks]))

    @filter.command("今日里番", alias={"里番今日"})
    async def rank_day(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self._rank_event(event, "今日", arg):
            yield r

    @filter.command("本周里番", alias={"里番本周"})
    async def rank_week(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self._rank_event(event, "本周", arg):
            yield r

    @filter.command("本月里番", alias={"里番本月"})
    async def rank_month(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self._rank_event(event, "本月", arg):
            yield r

    async def _rank_event(self, event, kind: str, arg: str):
        n = 20
        genre_key = ""
        for token in str(arg or "").split():
            low = token.lower()
            if token.isdigit():
                n = max(1, min(int(token), 30))
            elif low in GENRES:
                genre_key = GENRES[low]
        sort = RANKS.get(kind, "本日排行")
        try:
            items = await self._items_rank(sort, genre_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[hanime] 排行抓取失败：%r", exc)
            yield event.plain_result("排行榜打不开，稍后再试～")
            return
        if not items:
            yield event.plain_result("没抓到排行～")
            return
        picked = items[:n]
        label = f"{kind}排行" + (f" · {genre_key}" if genre_key else "")
        chain = await self._deliver(event, picked, f"🏆 里番{label}（前 {len(picked)} 部）")
        if chain is not None:
            yield event.chain_result(chain)

    # ---------------------------------------------------------------- 群列表
    async def _all_groups(self) -> list[str]:
        raw = self._opt("weekly_push_groups", "all")
        if isinstance(raw, list) and raw:
            return [str(g).strip() for g in raw if str(g).strip()]
        if isinstance(raw, str) and raw.strip() and raw.strip().lower() != "all":
            return [g.strip() for g in re.split(r"[,，\s]+", raw) if g.strip()]
        res = await self._action("get_group_list", {})
        groups = res.get("data") or []
        if isinstance(groups, dict):
            groups = groups.get("groups") or []
        return [str(g.get("group_id")) for g in groups if isinstance(g, dict) and g.get("group_id")]

    # ---------------------------------------------------------------- 推送
    async def initialize(self):
        if str(self._opt("push_enabled", "false")).strip().lower() in ("true", "1", "on", "yes"):
            self._task = asyncio.create_task(self._push_loop())
            logger.info("[hanime] 每日推送已启动：%s", self._opt("push_time", "21:00"))
        if str(self._opt("weekly_push_enabled", "false")).strip().lower() in ("true", "1", "on", "yes"):
            self._weekly_task = asyncio.create_task(self._weekly_loop())
            logger.info(
                "[hanime] 每周预告推送已启动：周%s %s → %s",
                self._opt("weekly_push_day", "sun"),
                self._opt("weekly_push_time", "21:00"),
                self._opt("weekly_push_groups", "all"),
            )

    async def terminate(self):
        for t in (getattr(self, "_task", None), getattr(self, "_weekly_task", None)):
            if t and not t.done():
                t.cancel()

    def _targets(self) -> list[str]:
        raw = self._opt("push_targets", [OWNER_UMO])
        if isinstance(raw, str):
            parts = [p.strip() for p in re.split(r"[,，\s]+", raw) if p.strip()]
        elif isinstance(raw, list):
            parts = [str(p).strip() for p in raw]
        else:
            parts = []
        return [OWNER_UMO if p in ("owner", "主人") else p for p in parts] or [OWNER_UMO]

    def _push_times(self) -> list[tuple[int, int]]:
        raw = self._opt("push_times", None) or self._opt("push_time", "07:00")
        if isinstance(raw, str):
            parts = [x.strip() for x in re.split(r"[,，\s]+", raw) if x.strip()]
        elif isinstance(raw, list):
            parts = [str(x).strip() for x in raw]
        else:
            parts = []
        times: list[tuple[int, int]] = []
        for part in parts:
            hh, _, mm = part.partition(":")
            try:
                times.append((int(hh), int(mm or 0)))
            except Exception:  # noqa: BLE001
                continue
        return sorted(set(times)) or [(7, 0), (19, 0)]

    async def _push_loop(self) -> None:
        while True:
            try:
                now = datetime.now()
                cands = []
                for hh, mm in self._push_times():
                    t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                    if t <= now:
                        t += timedelta(days=1)
                    cands.append(t)
                target = min(cands)
                wait = (target - now).total_seconds()
                logger.info("[hanime] 下次每日推送：%s", target.strftime("%m-%d %H:%M"))
                await asyncio.sleep(max(30, wait))
                await self._push_daily_once()
                await asyncio.sleep(90)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[hanime] 每日推送循环异常：%r", exc)
                await asyncio.sleep(300)

    async def _weekly_loop(self) -> None:
        days = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        while True:
            try:
                target_wd = days.get(str(self._opt("weekly_push_day", "sun")).strip().lower()[:3], 6)
                hh, _, mm = str(self._opt("weekly_push_time", "21:00")).partition(":")
                now = datetime.now()
                ahead = (target_wd - now.weekday()) % 7
                target = (now + timedelta(days=ahead)).replace(
                    hour=int(hh), minute=int(mm or 0), second=0, microsecond=0
                )
                if target <= now:
                    target += timedelta(days=7)
                wait = (target - now).total_seconds()
                logger.info("[hanime] 下次周推送：%s（%.1f 小时后）", target.strftime("%m-%d %H:%M"), wait / 3600)
                await asyncio.sleep(max(30, wait))
                await self._push_preview_once()
                await asyncio.sleep(120)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[hanime] 周推送循环异常：%r", exc)
                await asyncio.sleep(300)

    async def _push_daily_once(self) -> None:
        try:
            n = max(1, min(int(self._opt("push_count", 20)), 20))
        except Exception:
            n = 5
        try:
            items = [it for it in await self._items(NEW_URL) if it.get("title")][:n]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[hanime] 每日推送抓取失败：%r", exc)
            return
        if not items:
            return
        header = f"🔞 今日里番新作（前 {len(items)} 部）"
        for umo in self._targets():
            is_dm = "FriendMessage" in umo
            tid = int(umo.rsplit(":", 1)[-1])
            kw = {"private_id": tid} if is_dm else {"group_id": tid}
            ok, how = await self._send_forward(items, header, with_cover=True, **kw)
            logger.info("[hanime] 每日推送 %s：%s(%s)", umo, ok, how)
            await asyncio.sleep(2.0)

    async def _push_preview_once(self) -> None:
        try:
            n = max(1, min(int(self._opt("weekly_push_count", 10)), 20))
        except Exception:
            n = 10
        try:
            items = (await self._items_preview())[:n]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[hanime] 预告推送抓取失败：%r", exc)
            return
        if not items:
            return
        header = f"📅 本周里番预告（{len(items)} 部）"
        groups = await self._all_groups()
        logger.info("[hanime] 预告推送：%s 部 → %s 个群", len(items), len(groups))
        for gid in groups:
            ok, how = await self._send_forward(items, header, group_id=int(gid), with_cover=True)
            logger.info("[hanime] 预告推送 群%s：%s(%s)", gid, ok, how)
            await asyncio.sleep(2.0)

    # ---------------------------------------------------------------- 群列表
    async def _all_groups(self) -> list[str]:
        raw = self._opt("weekly_push_groups", "all")
        if isinstance(raw, list) and raw:
            return [str(g).strip() for g in raw if str(g).strip()]
        if isinstance(raw, str) and raw.strip() and raw.strip().lower() != "all":
            return [g.strip() for g in re.split(r"[,，\s]+", raw) if g.strip()]
        res = await self._action("get_group_list", {})
        groups = res.get("data") or []
        if isinstance(groups, dict):
            groups = groups.get("groups") or []
        return [str(g.get("group_id")) for g in groups if isinstance(g, dict) and g.get("group_id")]

    # ---------------------------------------------------------------- 推送
    async def initialize(self):
        if str(self._opt("push_enabled", "false")).strip().lower() in ("true", "1", "on", "yes"):
            self._task = asyncio.create_task(self._push_loop())
            logger.info("[hanime] 每日推送已启动：%s", self._opt("push_time", "21:00"))
        if str(self._opt("weekly_push_enabled", "false")).strip().lower() in ("true", "1", "on", "yes"):
            self._weekly_task = asyncio.create_task(self._weekly_loop())
            logger.info(
                "[hanime] 每周预告推送已启动：周%s %s → %s",
                self._opt("weekly_push_day", "sun"),
                self._opt("weekly_push_time", "21:00"),
                self._opt("weekly_push_groups", "all"),
            )

    async def terminate(self):
        for t in (getattr(self, "_task", None), getattr(self, "_weekly_task", None)):
            if t and not t.done():
                t.cancel()

    def _targets(self) -> list[str]:
        raw = self._opt("push_targets", [OWNER_UMO])
        if isinstance(raw, str):
            parts = [p.strip() for p in re.split(r"[,，\s]+", raw) if p.strip()]
        elif isinstance(raw, list):
            parts = [str(p).strip() for p in raw]
        else:
            parts = []
        return [OWNER_UMO if p in ("owner", "主人") else p for p in parts] or [OWNER_UMO]

    def _push_times(self) -> list[tuple[int, int]]:
        raw = self._opt("push_times", None) or self._opt("push_time", "07:00")
        if isinstance(raw, str):
            parts = [x.strip() for x in re.split(r"[,，\s]+", raw) if x.strip()]
        elif isinstance(raw, list):
            parts = [str(x).strip() for x in raw]
        else:
            parts = []
        times: list[tuple[int, int]] = []
        for part in parts:
            hh, _, mm = part.partition(":")
            try:
                times.append((int(hh), int(mm or 0)))
            except Exception:  # noqa: BLE001
                continue
        return sorted(set(times)) or [(7, 0), (19, 0)]

    async def _push_loop(self) -> None:
        while True:
            try:
                now = datetime.now()
                cands = []
                for hh, mm in self._push_times():
                    t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                    if t <= now:
                        t += timedelta(days=1)
                    cands.append(t)
                target = min(cands)
                wait = (target - now).total_seconds()
                logger.info("[hanime] 下次每日推送：%s", target.strftime("%m-%d %H:%M"))
                await asyncio.sleep(max(30, wait))
                await self._push_daily_once()
                await asyncio.sleep(90)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[hanime] 每日推送循环异常：%r", exc)
                await asyncio.sleep(300)

    async def _weekly_loop(self) -> None:
        days = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        while True:
            try:
                target_wd = days.get(str(self._opt("weekly_push_day", "sun")).strip().lower()[:3], 6)
                hh, _, mm = str(self._opt("weekly_push_time", "21:00")).partition(":")
                now = datetime.now()
                ahead = (target_wd - now.weekday()) % 7
                target = (now + timedelta(days=ahead)).replace(
                    hour=int(hh), minute=int(mm or 0), second=0, microsecond=0
                )
                if target <= now:
                    target += timedelta(days=7)
                wait = (target - now).total_seconds()
                logger.info("[hanime] 下次周推送：%s（%.1f 小时后）", target.strftime("%m-%d %H:%M"), wait / 3600)
                await asyncio.sleep(max(30, wait))
                await self._push_preview_once()
                await asyncio.sleep(120)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[hanime] 周推送循环异常：%r", exc)
                await asyncio.sleep(300)
