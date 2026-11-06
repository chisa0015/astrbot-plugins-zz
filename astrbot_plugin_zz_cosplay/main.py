"""随机 cos 图：cosplay8（图集）+ 绅士会所（r18 图集）双源，下载后以图片消息发送。

命令：
    cos / 随机cos / 来张cos / cos图         → 默认源（cosplay8 图集）
    cos r18                                 → 绅士会所 r18 随机图集
    cos cos8 / cos club                     → 指定站点

要点：
- 图片先下到本地再发（QQ 侧访问不了外链图床）；
- 网络走「本地代理优先 → 直连兜底」，适配 fake-IP 环境；
- cosplay8 的图集页把图片列表内嵌在 `const images = [...]` 里，直接正则取。
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from pathlib import Path

import astrbot.api.message_components as Comp
import httpx
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
PROXY = "http://127.0.0.1:7890"
CACHE_DIR = Path(r"D:\DSK\BOT\runtime\cos_cache")

COS8_HOST = "http://www.cosplay8.com"
COS8_CATS = ("neicos", "waicos", "sfxz", "lolita", "hanfu")
CLUB_HOST = "https://www.hentaiclub.net"
CLUB_SORT = ("r18", "r15")

_IMG_SRC = re.compile(r'<img[^>]+src="([^"]+)"', re.I)
_COS8_IMAGES = re.compile(r"(?:const|var|let)\s+images\s*=\s*\[(.*?)\]", re.S)
_QUOTED = re.compile(r"""['"]([^'"]+)['"]""")
_CLUB_IMAGES = re.compile(r"https://cdn\.sshs\.rip/[^\s\"'<>]+?\.(?:webp|jpe?g|png)", re.I)


@register(
    "astrbot_plugin_zz_cosplay",
    "yesha",
    "随机 cos 图（cosplay8 / 绅士会所）",
    "1.1.0",
    "",
)
class CosplayPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self._config = config
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

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

    @property
    def default_source(self) -> str:
        return str(self._opt("source", "hentaiclub")).strip().lower()

    @property
    def club_sort(self) -> str:
        return str(self._opt("club_sort", "r18")).strip().lower()

    # ---------------------------------------------------------------- 网络
    def _client(self, proxy: str | None, timeout: float = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": UA},
            verify=False,
            proxy=proxy,
            trust_env=False,
        )

    async def _get_text(self, url: str, referer: str | None = None) -> str:
        headers = {"Referer": referer} if referer else {}
        last: Exception | None = None
        for proxy in (PROXY, None):
            for _ in range(2):
                try:
                    async with self._client(proxy) as cli:
                        resp = await cli.get(url, headers=headers)
                    if resp.status_code == 200 and resp.text:
                        return resp.text
                    last = RuntimeError(f"HTTP {resp.status_code}")
                except Exception as exc:  # noqa: BLE001
                    last = exc
                await asyncio.sleep(0.3)
        raise RuntimeError(f"页面抓取失败 {url}：{last!r}"[:220])

    async def _download(self, url: str) -> Path | None:
        if url.startswith("//"):
            url = "https:" + url
        last: Exception | None = None
        # 按域名给 Referer：hentaiclub 的图床 cdn.sshs.rip 不带参考页会 403
        if "sshs.rip" in url or "hentaiclub" in url:
            ref = "https://www.hentaiclub.net/"
        else:
            ref = COS8_HOST + "/"
        for proxy in (PROXY, None):
            try:
                async with self._client(proxy, timeout=60.0) as cli:
                    resp = await cli.get(url, headers={"Referer": ref, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
                if resp.status_code == 200 and len(resp.content) > 4096:
                    suffix = Path(url.split("?")[0]).suffix or ".jpg"
                    if len(suffix) > 5:
                        suffix = ".jpg"
                    out = CACHE_DIR / f"cos_{int(time.time() * 1000)}_{random.randint(100, 999)}{suffix}"
                    out.write_bytes(resp.content)
                    return out
                last = RuntimeError(f"HTTP {resp.status_code}")
            except Exception as exc:  # noqa: BLE001
                last = exc
        logger.warning("[cos] 下载失败 %s：%r", url, last)
        return None

    # ---------------------------------------------------------------- 源 1：cosplay8
    async def _cosplay8(self, limit: int) -> list[str]:
        for _ in range(3):
            cat = random.choice(COS8_CATS)
            page = random.randint(1, 15)
            try:
                listing = await self._get_text(f"{COS8_HOST}/list/{cat}/{page}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[cos] cosplay8 列表失败：%r", exc)
                continue
            albums = list(dict.fromkeys(re.findall(r'href="(/news/[a-z]+/\d+)"', listing)))
            if not albums:
                continue
            album = COS8_HOST + random.choice(albums)
            try:
                html = await self._get_text(album, referer=f"{COS8_HOST}/list/{cat}/{page}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[cos] cosplay8 图集失败：%r", exc)
                continue
            m = _COS8_IMAGES.search(html)
            urls = _QUOTED.findall(m.group(1)) if m else []
            urls = [u if u.startswith("http") else COS8_HOST + u for u in urls if u]
            if not urls:
                urls = [u for u in _IMG_SRC.findall(html) if "ciyuandao.com/works" in u]
            if urls:
                random.shuffle(urls)
                logger.info("[cos] cosplay8：%s 共 %s 张", album, len(urls))
                return urls[:limit]
        return []

    # ---------------------------------------------------------------- 源 2：绅士会所
    async def _hentaiclub(self, limit: int) -> list[str]:
        sort = self.club_sort if self.club_sort in CLUB_SORT else "r18"
        for _ in range(3):
            try:
                listing = await self._get_text(f"{CLUB_HOST}/sort/{sort}.html")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[cos] club 列表失败：%r", exc)
                continue
            items = list(dict.fromkeys(re.findall(rf'href="(?:https://www\.hentaiclub\.net)?(/{sort}/\d+\.html)"', listing)))
            if not items:
                continue
            item = CLUB_HOST + random.choice(items)
            try:
                html = await self._get_text(item, referer=f"{CLUB_HOST}/sort/{sort}.html")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[cos] club 图集失败：%r", exc)
                continue
            urls = list(dict.fromkeys(_CLUB_IMAGES.findall(html)))
            if urls:
                random.shuffle(urls)
                logger.info("[cos] club：%s 共 %s 张", item, len(urls))
                return [u if u.startswith("http") else "https:" + u for u in urls][:limit]
        return []

    # ---------------------------------------------------------------- 命令
    async def _handle(self, event: AstrMessageEvent, raw: str = ""):
        arg = str(raw or "").strip().lower()
        count = 1
        for token in arg.split():
            if token.isdigit():
                count = max(1, min(int(token), 5))
        source = self.default_source
        if "r18" in arg or "club" in arg or "绅士" in arg:
            source = "hentaiclub"
        elif "cos8" in arg or "cosplay8" in arg:
            source = "cosplay8"

        try:
            urls = await (self._hentaiclub(count) if source == "hentaiclub" else self._cosplay8(count))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cos] 拉取失败：%r", exc)
            urls = []
        if not urls:
            yield event.plain_result("这次没抓图下来，稍后再试（站点偶尔抽风）～")
            return

        chain = []
        for url in urls:
            path = await self._download(url)
            if path is not None:
                chain.append(Comp.Image(file=str(path)))
        if not chain:
            yield event.plain_result("图下不下来，代理可能没开…")
            return
        logger.info("[cos] 发送 %s 张（源 %s）", len(chain), source)
        yield event.chain_result(chain)

    @filter.command("cos")
    async def cos_cmd(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self._handle(event, arg):
            yield r

    @filter.command("随机cos")
    async def cos_cmd2(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self._handle(event, arg):
            yield r

    @filter.command("来张cos")
    async def cos_cmd3(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self._handle(event, arg):
            yield r

    @filter.command("cos图")
    async def cos_cmd4(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self._handle(event, arg):
            yield r


    # ---------------------------------------------------------------- 群聊免唤醒入口
    @filter.regex(r"(?i)^(cos|随机cos|来张cos|cos图)(\s+\S+)?$")
    async def cos_group(self, event: AstrMessageEvent):
        """群聊直接发 cos / cos 3 也能触发（RegexFilter 不受 wake_prefix 限制）。"""
        msg = (event.message_str or "").strip()
        arg = ""
        for kw in ("随机cos", "来张cos", "cos图", "cos"):
            if msg.lower().startswith(kw):
                arg = msg[len(kw):].strip()
                break
        async for r in self._handle(event, arg):
            yield r
        event.stop_event()  # 防止继续走 LLM 闲聊
