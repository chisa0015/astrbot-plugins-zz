"""今日运势卡：随机二次元壁纸 + 吉凶等级 + 五项指数 + 宜忌 + 幸运元素，渲染成图片发送。

命令：
    运势卡 / 抽运势 / 今日运势卡      → 生成一张运势卡（自动用发指令人的昵称）
    运势卡 名字                       → 指定署名

等级口径与 setu 插件一致（0~7 星权重）：凶 / 末吉 / 末小吉 / 小吉 / 中吉 / 吉 / 大吉 / 超大吉
壁纸默认取 loliapi 随机 ACG 图（需要代理）；取不到就退化成纯色底，卡片照样能出。
"""

from __future__ import annotations

import asyncio
import io
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path

import astrbot.api.message_components as Comp
import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain

WEIGHTS = [0.1, 0.15, 0.2, 0.25, 0.15, 0.12, 0.07, 0.005]
TITLES = ["凶", "末吉", "末小吉", "小吉", "中吉", "吉", "大吉", "超大吉"]
ADVICE = [
    "宜静观其变，别硬碰硬。",
    "状态平稳，适合处理积压的小事。",
    "比昨天好一点，先做最难的那件。",
    "稳中有进，按计划走就对了。",
    "状态不错，适合推进要紧的事。",
    "势头正旺，主动出击会有回应。",
    "诸事顺遂，想做的事现在就去。",
    "万事皆成，今天你说什么都对。",
]
GOOD = ["吃顿好的", "和朋友聊天", "摸鱼", "早睡", "听歌", "散步", "整理桌面", "喝奶茶",
        "发呆", "看番", "洗个热水澡", "给喜欢的人发消息"]
BAD = ["熬夜", "冲动消费", "跟人吵架", "硬撑", "拖延", "刷手机到凌晨", "喝冰的", "签合同",
       "翻旧账", "赌运气"]
LUCKY_COLORS = [("朱红", (196, 62, 58)), ("米白", (240, 234, 220)), ("月蓝", (92, 138, 196)),
                ("墨绿", (62, 110, 88)), ("琥珀", (206, 148, 66)), ("紫藤", (150, 116, 190)),
                ("浅粉", (232, 152, 168)), ("灰蓝", (110, 128, 150))]
LUCKY_OBJECTS = ["一杯热饮", "耳机", "橡皮筋", "旧照片", "便利贴", "钥匙扣", "小零食", "笔记本"]
BARS = [("爱情", (232, 120, 160)), ("事业", (108, 164, 226)), ("学业", (150, 132, 216)),
        ("财运", (222, 196, 108)), ("健康", (110, 196, 170))]
GAMES = [
    # ==== 国产二次元手游 / 端游
    ("原神", "国产 · 跑图解压"),
    ("崩坏：星穹铁道", "国产 · 剧情推进"),
    ("绝区零", "国产 · 打一轮空洞"),
    ("鸣潮", "国产 · 声骸刷起来"),
    ("明日方舟", "国产 · 动脑一局"),
    ("重返未来：1999", "国产 · 剧情沉浸"),
    ("少女前线2：追放", "国产 · 战术一局"),
    ("无期迷途", "国产 · 关卡推一推"),
    ("幻塔", "国产 · 逛图摸鱼"),
    ("战双帕弥什", "国产 · 闪避爽一把"),
    ("深空之眼", "国产 · 连携一波"),
    ("崩坏3", "国产 · 深渊打一层"),
    # ==== 日系手游
    ("蔚蓝档案", "日系 · 轻松日常"),
    ("赛马娘", "日系 · 养一匹"),
    ("公主连结Re:Dive", "日系 · 公会战摸鱼"),
    ("Fate/Grand Order", "日系 · 刷个本"),
    ("世界计划", "日系 · 打两首歌"),
    ("学园偶像大师", "日系 · 练一次偶像"),
    ("绯染天空", "日系 · 剧情泪目"),
    # ==== 韩系 / 海外
    ("胜利女神：妮姬", "韩系 · 一发十连"),
    ("碧蓝航线", "海外 · 挂机养老"),
    ("明日方舟：终末地", "海外 · 建个基地"),
    # ==== 单机二次元
    ("女神异闻录5 皇家版", "单机 · 打一次殿堂"),
    ("破晓传说", "单机 · 推一段支线"),
    ("异度神剑3", "单机 · 长途冒险"),
    ("火焰纹章：风花雪月", "单机 · 走一格算半天"),
    ("尼尔：机械纪元", "单机 · 打一段悲恋"),
    ("十三机兵防卫圈", "单机 · 剧情烧脑"),
    ("莱莎的炼金工房", "单机 · 炼金一小时"),
    ("苏菲的炼金工房2", "单机 · 调和上头"),
    ("蓝色反射：幻舞少女之剑", "单机 · 换装战斗"),
    ("弹丸论破", "单机 · 推理一局"),
    ("狂战传说", "单机 · 连段爽"),
    # ==== Galgame / 视觉小说
    ("ATRI -My Dear Moments-", "galgame · 一小时泪目"),
    ("千恋＊万花", "galgame · 柚子社治愈"),
    ("白色相簿2", "galgame · 自找胃疼"),
    ("Fate/stay night", "galgame · 补原作"),
    ("CLANNAD", "galgame · 备好纸巾"),
    ("Summer Pockets", "galgame · 夏日氛围"),
    ("9-nine-", "galgame · 悬疑一集"),
    ("苍之彼方的四重奏", "galgame · 空战青春"),
    ("星空列车与白的旅行", "galgame · 短篇治愈"),
    ("灰色的果实", "galgame · 剧情重口"),
]


ANIME_PUBLISHERS = (
    "bandai", "namco", "aniplex", "cygames", "yostar", "mihoyo", "hoyoverse",
    "kuro game", "hypergryph", "sega", "square enix", "bushiroad", "aiming",
    "klab", "gree", "mixi", "nexon", "netmarble", "kakao", "cover corp",
    "hololive", "good smile", "marvelous", "bilibili", "longcheng", "archosaur",
    "papergames", "efun", "applibot", "colopl", "gumi", "yoozoo", "lbxx",
    "shueisha", "kadokawa", "type-moon", "visual arts", "key", "prototype",
    "compass", "dena", "akatsuki", "wfs", "wright flyer", "team caravan",
    "sunrise", "toei", "tatsunoko", "mappa", "ufotable",
    "com2us", "clyre", "gravity", "qookka", "genmugame", "picorea",
    "adhoc studio", "aladdin games", "pan thera", "tactile",
    "yostar games", "gumi inc", "qoo",
)

FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"
KOREAN_FONT = r"C:\Windows\Fonts\malgun.ttf"
OUT_DIR = Path(r"D:\DSK\BOT\runtime\fortune")
PROXY = "http://127.0.0.1:7890"
W, H = 900, 1580
PANEL_TOP = 840


@register(
    "astrbot_plugin_zz_fortune",
    "yesha",
    "今日运势卡：壁纸 + 星级 + 五项指数 + 宜忌 + 幸运元素",
    "1.0.0",
    "",
)
class FortuneCardPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self._config = config
        OUT_DIR.mkdir(parents=True, exist_ok=True)

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

    # ---------------------------------------------------------------- 壁纸
    async def initialize(self) -> None:
        """先读本地缓存（秒开），数据旧了再后台刷新。"""
        _cache_load_disk()
        try:
            stale = _cache_age("hottest") > _DISK_TTL or _cache_age("qoo") > _DISK_TTL
            if stale or not (_GAME_CACHE.get("qoo") or _GAME_CACHE.get("hottest")):
                asyncio.create_task(self._warm_cache())
            else:
                logger.info("[fortune] 本地游戏缓存命中，跳过联网抓取")
        except Exception:  # noqa: BLE001
            pass

    async def _warm_cache(self) -> None:
        try:
            await self._pick_game()
        except Exception as exc:  # noqa: BLE001
            logger.info("[fortune] 预热游戏失败：%r", exc)
        try:
            await self._pick_galgame()
        except Exception as exc:  # noqa: BLE001
            logger.info("[fortune] 预热GAL失败：%r", exc)
        logger.info("[fortune] 缓存预热完成")

    async def _wallpaper(self) -> Image.Image | None:
        primary = str(self._opt("wallpaper_url", "https://t.alcy.cc/pc"))
        urls = [primary, "https://t.alcy.cc/pc", "https://www.loliapi.com/acg/"]
        urls = list(dict.fromkeys(u for u in urls if u))
        proxy = str(self._opt("proxy", PROXY)) or None
        for url in urls:
            for attempt in range(2):
                for p in (proxy, None):
                    try:
                        async with httpx.AsyncClient(
                            timeout=20, verify=False, proxy=p, trust_env=False,
                            follow_redirects=True,
                            headers={"User-Agent": "Mozilla/5.0 " + str(attempt)},
                        ) as cli:
                            r = await cli.get(url)
                        if r.status_code != 200 or "image" not in (r.headers.get("content-type") or ""):
                            continue
                        if len(r.content) < 15000:
                            continue
                        im = Image.open(io.BytesIO(r.content)).convert("RGB")
                        if min(im.size) >= 600:
                            logger.info("[fortune] 壁纸来源：%s", url)
                            return im
                    except Exception:  # noqa: BLE001
                        continue
        logger.warning("[fortune] 壁纸全部失败，使用纯色底")
        return None

    # ---------------------------------------------------------------- QooApp 游戏池
    async def _qoo_games(self) -> list[tuple[str, str]]:
        """从 QooApp 游戏日历拉本月新游，转成 (名字, 理由) 池；失败返回空。"""
        cache = getattr(self, "_qoo_cache", None)
        if cache and time.time() - cache[1] < 21600:
            return cache[0]
        base = str(self._opt("qoo_calendar", "https://www.qoo-app.com/api/calender/games"))
        proxy = str(self._opt("proxy", PROXY)) or None
        months = [datetime.now().strftime("%Y-%m"), ""]
        pool: list[tuple[str, str]] = []
        seen: set[str] = set()
        for month in months:
            url = base + (f"?date={month}" if month else "")
            data = None
            for pr in (proxy, None):
                try:
                    async with httpx.AsyncClient(timeout=20, verify=False, proxy=pr, trust_env=False,
                                                 follow_redirects=True,
                                                 headers={"User-Agent": "Mozilla/5.0",
                                                          "Referer": "https://www.qoo-app.com/"}) as cli:
                        r = await cli.get(url)
                    if r.status_code == 200 and "json" in (r.headers.get("content-type") or ""):
                        data = r.json()
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not data:
                continue
            entries: list[dict] = []
            for items in (data.get("coming") or {}).values():
                if isinstance(items, list):
                    entries.extend(items)
            entries.extend(data.get("upcoming") or [])
            for it in entries:
                if not isinstance(it, dict):
                    continue
                name = (it.get("display_name") or it.get("name") or it.get("app_name") or "").strip()
                name = re.sub(r"\s+", " ", name)
                if not name or len(name) > 28:
                    continue
                key = re.sub(r"[【\[（(].*?[】\]）)]", "", name).strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)

                company = ((it.get("company") or {}) or {}).get("name") or ""
                comp_low = company.lower()
                if not any(k in comp_low for k in ANIME_PUBLISHERS):
                    continue

                def short_date(v: str) -> str:
                    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", v or "")
                    return f"{m.group(2)}-{m.group(3)}" if m else ""

                reason = ""
                if it.get("gp_published_date"):
                    d = short_date(it["gp_published_date"])
                    reason = f"已上线 · {d}" if d else "已上线"
                elif it.get("pre_release_date"):
                    d = short_date(it["pre_release_date"])
                    reason = f"即将上线 · {d}" if d else "即将上线"
                elif it.get("pre_date") and it["pre_date"] not in ("尚未公開", "未公開"):
                    reason = f"预定 · {it['pre_date']}"
                if company:
                    reason = f"{reason}｜{company[:10]}" if reason else company[:12]
                if not reason:
                    reason = "Qoo新游 · 试一手"
                pool.append((name, reason))
        if len(pool) < 3:
            logger.info("[fortune] QooApp 二次元池只有 %s 款，放宽为全量", len(pool))
            pool = []
            for month in months:
                url = base + (f"?date={month}" if month else "")
                data = None
                for pr in (proxy, None):
                    try:
                        async with httpx.AsyncClient(timeout=20, verify=False, proxy=pr, trust_env=False,
                                                     follow_redirects=True,
                                                     headers={"User-Agent": "Mozilla/5.0",
                                                              "Referer": "https://www.qoo-app.com/"}) as cli:
                            r = await cli.get(url)
                        if r.status_code == 200 and "json" in (r.headers.get("content-type") or ""):
                            data = r.json()
                            break
                    except Exception:  # noqa: BLE001
                        continue
                if not data:
                    continue
                entries: list[dict] = []
                for items in (data.get("coming") or {}).values():
                    if isinstance(items, list):
                        entries.extend(items)
                entries.extend(data.get("upcoming") or [])
                for it in entries:
                    if not isinstance(it, dict):
                        continue
                    name = (it.get("display_name") or it.get("name") or it.get("app_name") or "").strip()
                    if not name or len(name) > 28 or name in seen:
                        continue
                    seen.add(name)
                    pool.append((name, "Qoo新游 · 试一手"))
        if pool:
            self._qoo_cache = (pool, time.time())
            logger.info("[fortune] QooApp 游戏池：%s 款", len(pool))
        return pool

    TOUCHGAL_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }

    async def _touchgal_hashes(self) -> list[str]:
        """TouchGal 站点地图 → 游戏页 hash 列表（缓存 24 小时）。"""
        cache = getattr(self, "_tg_hashes", None)
        if cache and time.time() - cache[1] < 86400:
            return cache[0]
        url = str(self._opt("touchgal_sitemap", "https://www.touchgal.ink/sitemap.xml"))
        proxy = str(self._opt("proxy", PROXY)) or None
        xml = ""
        for pr in (proxy, None):
            try:
                async with httpx.AsyncClient(timeout=45, verify=False, proxy=pr, trust_env=False,
                                             follow_redirects=True, headers=self.TOUCHGAL_HEADERS) as cli:
                    r = await cli.get(url)
                if r.status_code == 200 and "<urlset" in r.text:
                    xml = r.text
                    break
            except Exception:  # noqa: BLE001
                continue
        hashes = re.findall(r"https://www\.touchgal\.ink/([0-9a-f]{8})<", xml)
        hashes = list(dict.fromkeys(hashes))
        if hashes:
            self._tg_hashes = (hashes, time.time())
            logger.info("[fortune] TouchGal 游戏页：%s 个", len(hashes))
        return hashes

    async def _touchgal_game(self) -> tuple[str, str] | None:
        """随机取一个 TouchGal 游戏页，读 og:title + 发售时间。"""
        base = str(self._opt("touchgal_base", "https://www.touchgal.ink")).rstrip("/")
        proxy = str(self._opt("proxy", PROXY)) or None
        try:
            hashes = await self._touchgal_hashes()
        except Exception:  # noqa: BLE001
            hashes = []
        if not hashes:
            return None
        for _ in range(3):
            key = random.choice(hashes)
            for pr in (proxy, None):
                try:
                    async with httpx.AsyncClient(timeout=20, verify=False, proxy=pr, trust_env=False,
                                                 follow_redirects=True, headers=self.TOUCHGAL_HEADERS) as cli:
                        r = await cli.get(f"{base}/{key}")
                    if r.status_code != 200 or len(r.text) < 20000:
                        continue
                    og = re.search(r'property="og:title"\s+content="([^"]*)"', r.text)
                    if not og:
                        continue
                    name = re.split(r"\s*[|｜]\s*", og.group(1))[0].strip()
                    name = re.sub(r"\s+", " ", name)
                    if not name or len(name) > 28:
                        continue
                    plain = re.sub(r"<[^>]+>", " ", r.text)
                    plain = re.sub(r"\s+", " ", plain)
                    dm = re.search(r"(?:发售时间|發售時間|发售日期)[:：]?\s*(\d{4}-\d{2}-\d{2})", plain)
                    reason = f"galgame · {dm.group(1)}" if dm else "galgame · TouchGal"
                    return name, reason
                except Exception:  # noqa: BLE001
                    continue
        return None

    async def _kungal_games(self) -> list[tuple[str, str]]:
        """鲲 Galgame 资料库（kungal.com/gallib?sortField=time）→ (名字, 理由) 池。"""
        cache = getattr(self, "_gal_cache", None)
        if cache and time.time() - cache[1] < 21600:
            return cache[0]
        base = str(self._opt("galgame_url", "https://www.kungal.com/gallib?sortField=time"))
        proxy = str(self._opt("proxy", PROXY)) or None
        pool: list[tuple[str, str]] = []
        seen: set[str] = set()
        for page in range(1, 4):  # 抓 3 页，池子约 70 部
            url = base if page == 1 else f"{base}&page={page}"
            html = ""
            for pr in (None, proxy):
                try:
                    async with httpx.AsyncClient(timeout=25, verify=False, proxy=pr, trust_env=False,
                                                 follow_redirects=True,
                                                 headers={"User-Agent": "Mozilla/5.0"}) as cli:
                        r = await cli.get(url)
                    if r.status_code == 200 and len(r.text) > 50000:
                        html = r.text
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not html:
                continue
            for m in re.finditer(r'href="(/galgame/\d+)"', html):
                chunk = html[m.start() : m.start() + 3200]
                nm = re.search(r'alt="([^"]{1,40})"', chunk)
                name = (nm.group(1) if nm else "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                dm = re.search(r'class="text-default-500 mt-1 text-xs">\s*([\d\-年月日]{4,12})\s*<', chunk)
                date = dm.group(1) if dm else ""
                pool.append((name, f"galgame · {date}" if date else "galgame · 推荐"))
        if pool:
            self._gal_cache = (pool, time.time())
            logger.info("[fortune] kungal galgame 池：%s 部", len(pool))
        return pool

    async def _pick_galgame(self) -> tuple[str, str] | None:
        # 优先 TouchGal（随机单页），失败再退 kungal
        try:
            picked = await self._touchgal_game()
            if picked:
                _cache_put("touchgal", [picked])
                return picked
        except Exception as exc:  # noqa: BLE001
            logger.info("[fortune] TouchGal 抽取失败：%r", exc)
        try:
            pool = await self._kungal_games()
        except Exception as exc:  # noqa: BLE001
            logger.info("[fortune] kungal 拉取失败：%r", exc)
            pool = []
        if pool:
            _cache_put("kungal", pool)
            return random.choice(pool)
        fallback = [g for g in GAMES if "galgame" in g[1].lower()]
        if fallback:
            _cache_put("kungal", fallback)
            return random.choice(fallback)
        return None

    async def _hottest_games_cached(self) -> list[tuple[str, str]]:
        cached = _cache_get("hottest")
        if cached is not None:
            return list(cached)  # type: ignore[arg-type]
        data = await self._hottest_games()
        if data:
            _cache_put("hottest", data)
        return data

    async def _hottest_games(self) -> list[tuple[str, str]]:
        """QooApp 人气最高榜（apps.qoo-app.com/hottest）→ (名字, 评分理由) 池。"""
        cache = getattr(self, "_hot_cache", None)
        if cache and time.time() - cache[1] < 21600:
            return cache[0]
        url = str(self._opt("qoo_hottest", "https://apps.qoo-app.com/hottest"))
        proxy = str(self._opt("proxy", PROXY)) or None
        html = ""
        for pr in (proxy, None):
            try:
                async with httpx.AsyncClient(timeout=25, verify=False, proxy=pr, trust_env=False,
                                             follow_redirects=True,
                                             headers={"User-Agent": "Mozilla/5.0"}) as cli:
                    r = await cli.get(url)
                if r.status_code == 200 and len(r.text) > 50000:
                    html = r.text
                    break
            except Exception:  # noqa: BLE001
                continue
        pool: list[tuple] = []
        if html:
            seen: set[str] = set()
            block = re.compile(
                r'<a class="qoo-app-item-small-v"\s+title="([^"]+)"[^>]*>(.*?)</a>', re.S
            )
            for m in block.finditer(html):
                title = m.group(1).strip()
                title = re.split(r"\s*\|\s*QooApp", title)[0].strip()
                # 把「| 日版 / 繁中版」拆到理由里
                region = ""
                if "|" in title:
                    head, _, tail = title.rpartition("|")
                    if len(tail.strip()) <= 6:
                        title, region = head.strip(), tail.strip()
                name = re.sub(r"\s+", " ", title)
                if not name or len(name) > 28 or name in seen:
                    continue
                seen.add(name)
                rm = re.search(r'width:\s*([\d.]+)em', m.group(2))
                rating = float(rm.group(1)) if rm else 0.0
                reason = f"人气 {rating:.1f}★" if rating else "人气榜"
                if region:
                    reason = f"{reason}｜{region}"
                pool.append((name, reason, rating))
        good = [(n, r) for n, r, sc in pool if sc >= 3.8]
        if len(good) < 8:
            good = [(n, r) for n, r, sc in pool if sc >= 3.0]
        if not good:
            good = [(n, r) for n, r, _ in pool]
        if good:
            self._hot_cache = (good, time.time())
            logger.info("[fortune] QooApp 人气榜池：%s 款（评分≥3.8 优先）", len(good))
        return good

    def _fast_game(self) -> tuple[str, str] | None:
        # 本地数据只要 24h 内就用，不再等联网
        hot = _cache_get("hottest", _DISK_TTL)
        if hot:
            return random.choice(list(hot))  # type: ignore[arg-type]
        pool = _cache_get("qoo", _DISK_TTL)
        if pool:
            return random.choice(list(pool))  # type: ignore[arg-type]
        return None

    def _fast_gal(self) -> tuple[str, str] | None:
        pool = _cache_get("touchgal", _DISK_TTL) or _cache_get("kungal", _DISK_TTL)
        if pool:
            return random.choice(list(pool))  # type: ignore[arg-type]
        return None

    async def _pick_game(self) -> tuple[str, str]:
        # 优先人气榜 → 再 QooApp 新游日历（二次元厂商） → 内置静态池
        try:
            hot = await self._hottest_games_cached()
        except Exception:  # noqa: BLE001
            hot = []
        if hot:
            return random.choice(hot)

        try:
            pool = await self._qoo_games()
        except Exception as exc:  # noqa: BLE001
            logger.info("[fortune] QooApp 池获取失败，用内置池：%r", exc)
            pool = []
        if pool:
            _cache_put("qoo", pool)
            return random.choice(pool)
        _cache_put("qoo", GAMES)
        return random.choice(GAMES)

    # ---------------------------------------------------------------- 渲染
    CASCADE_FILE = str(Path(__file__).with_name("lbpcascade_animeface.xml"))

    @classmethod
    def _cover(cls, im: Image.Image, w: int, h: int) -> Image.Image:
        """裁切成目标比例：优先让动漫人脸居中偏上，检测不到就上移取景。"""
        iw, ih = im.size
        scale = max(w / iw, h / ih)
        nw, nh = int(iw * scale + 0.5), int(ih * scale + 0.5)
        resized = im.resize((nw, nh), Image.LANCZOS)

        left, top = (nw - w) // 2, int((nh - h) * 0.18)
        try:
            import cv2
            import numpy as np

            if Path(cls.CASCADE_FILE).exists():
                arr = cv2.cvtColor(np.array(resized), cv2.COLOR_RGB2BGR)
                sw = min(640, nw)
                sh = max(1, int(sw * nh / nw))
                small = cv2.resize(arr, (sw, sh), interpolation=cv2.INTER_AREA)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                cas = cv2.CascadeClassifier(cls.CASCADE_FILE)
                faces = cas.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
                if len(faces):
                    fx, fy, fw, fh = max(faces, key=lambda r: int(r[2]) * int(r[3]))
                    cx = (fx + fw / 2) * nw / sw
                    cy = (fy + fh / 2) * nh / sh
                    left = int(cx - w / 2)
                    top = int(cy - h * 0.38)
        except Exception:  # noqa: BLE001
            pass

        left = max(0, min(left, nw - w))
        top = max(0, min(top, nh - h))
        return resized.crop((left, top, left + w, top + h))

    def _render(self, wall: Image.Image | None, grade: int, username: str, game: tuple[str, str] | None = None, gal: tuple[str, str] | None = None) -> Path:
        base_rgb = (18, 18, 20)
        canvas = Image.new("RGB", (W, H), base_rgb)

        # 壁纸铺满整张卡
        if wall is not None:
            canvas.paste(self._cover(wall, W, H), (0, 0))

        # 顶部压暗（保证标题可读）
        top_mask = Image.new("L", (1, 320))
        tp = top_mask.load()
        for y in range(320):
            tp[0, y] = int(max(0, 128 - y * 0.6))

        # 下半区：壁纸轻微模糊（保色不抢字）+ 半透明蒙层，壁纸始终可见
        blur_from = 690
        region = canvas.crop((0, blur_from, W, H)).filter(ImageFilter.GaussianBlur(7))
        feather = Image.new("L", (1, H - blur_from))
        for i in range(H - blur_from):
            feather.putpixel((0, i), min(255, int(255 * min(1.0, i / 120))))
        canvas.paste(region, (0, blur_from), feather.resize((W, H - blur_from)))

        scrim = Image.new("L", (1, H))
        for y in range(H):
            if y < blur_from:
                scrim.putpixel((0, y), 0)
            elif y < blur_from + 260:
                scrim.putpixel((0, y), int(124 * (y - blur_from) / 260))
            else:
                scrim.putpixel((0, y), 124)

        overlay = Image.new("RGB", (W, H), base_rgb)
        top_overlay = Image.new("RGB", (W, 320), base_rgb)
        canvas.paste(top_overlay, (0, 0), top_mask.resize((W, 320)))
        canvas.paste(overlay, (0, 0), scrim.resize((W, H)))

        draw = ImageDraw.Draw(canvas, "RGBA")
        f_head = ImageFont.truetype(FONT_BOLD, 34)
        f_nick = ImageFont.truetype(FONT_BOLD, 30)
        f_big = ImageFont.truetype(FONT_BOLD, 170)
        f_star = ImageFont.truetype(FONT_REG, 40)
        f_adv = ImageFont.truetype(FONT_REG, 30)
        f_lab = ImageFont.truetype(FONT_REG, 26)
        f_score = ImageFont.truetype(FONT_BOLD, 26)
        f_foot = ImageFont.truetype(FONT_REG, 22)
        f_badge = ImageFont.truetype(FONT_BOLD, 24)
        f_small = ImageFont.truetype(FONT_REG, 18)

        cream, gold, dim = (246, 238, 214), (232, 205, 150), (176, 170, 160)

        x = 48
        for ch in "今日运势":
            draw.text((x, 44), ch, font=f_head, fill=(255, 255, 255))
            x += 48
        today = datetime.now()
        wd = "一二三四五六日"[today.weekday()]
        draw.text((W - 48, 56), f"{today:%Y.%m.%d} · 周{wd}",
                  font=ImageFont.truetype(FONT_REG, 24), fill=(240, 240, 240), anchor="ra")

        stroke = 3
        scene_fill = (255, 255, 255)
        draw.text((48, 420), f"「{username}」的今日签", font=f_nick, fill=(*gold, 245),
                  stroke_width=stroke, stroke_fill=(0, 0, 0))
        draw.text((44, 436), TITLES[grade], font=f_big, fill=cream, stroke_width=4, stroke_fill=(0, 0, 0))
        stars5 = max(1, min(5, round(grade * 5 / 7)))
        draw.text((52, 676), "★" * stars5 + "☆" * (5 - stars5), font=f_star, fill=(*gold, 240),
                  stroke_width=2, stroke_fill=(0, 0, 0))
        draw.text((52, 742), ADVICE[grade], font=f_adv, fill=(scene_fill),
                  stroke_width=2, stroke_fill=(0, 0, 0))

        draw.line([(40, PANEL_TOP + 26), (W - 40, PANEL_TOP + 26)], fill=(255, 255, 255, 16), width=1)

        base = max(58, min(96, 62 + grade * 5))
        y = PANEL_TOP + 78
        for name, color in BARS:
            score = max(45, min(99, base + random.randint(-12, 10)))
            draw.text((48, y + 6), name, font=f_lab, fill=(236, 232, 224), stroke_width=2, stroke_fill=(0, 0, 0))
            bx, bw = 150, 560
            draw.rounded_rectangle([bx, y + 12, bx + bw, y + 26], radius=7, fill=(30, 30, 34, 150))
            draw.rounded_rectangle([bx, y + 12, bx + int(bw * score / 100), y + 26], radius=7, fill=color)
            draw.text((bx + bw + 40, y + 4), str(score), font=f_score, fill=(255, 255, 255), anchor="ra",
                      stroke_width=2, stroke_fill=(0, 0, 0))
            y += 58

        y += 14
        draw.rounded_rectangle([48, y, 90, y + 34], radius=7, fill=(58, 122, 108))
        draw.text((69, y + 17), "宜", font=f_badge, fill=(255, 255, 255), anchor="mm")
        draw.text((104, y + 4), "、".join(random.sample(GOOD, 2)), font=f_lab, fill=(255, 255, 255),
                  stroke_width=2, stroke_fill=(0, 0, 0))
        y += 50
        draw.rounded_rectangle([48, y, 90, y + 34], radius=7, fill=(150, 66, 66))
        draw.text((69, y + 17), "忌", font=f_badge, fill=(255, 255, 255), anchor="mm")
        draw.text((104, y + 4), "、".join(random.sample(BAD, 2)), font=f_lab, fill=(255, 255, 255),
                  stroke_width=2, stroke_fill=(0, 0, 0))

        y += 70
        cname, crgb = random.choice(LUCKY_COLORS)
        draw.text((48, y), "幸运色", font=f_foot, fill=(*dim, 240))
        draw.rounded_rectangle([132, y + 2, 156, y + 26], radius=5, fill=crgb)
        draw.text((166, y), cname, font=f_foot, fill=(226, 222, 214))
        draw.text((300, y), "幸运数字", font=f_foot, fill=(*dim, 240))
        draw.text((410, y), str(random.randint(1, 9)), font=f_foot, fill=(226, 222, 214))
        draw.text((470, y), "开运物", font=f_foot, fill=(*dim, 240))
        draw.text((546, y), random.choice(LUCKY_OBJECTS), font=f_foot, fill=(226, 222, 214))

        # 游戏行 + GALGAME 行（同一行排版，超宽自动缩字号/截断）
        def draw_row(label: str, name: str, reason: str, y_base: int, name_color=(255, 255, 255)) -> None:
            max_w = W - 96

            import os as _os

            def pick_font(txt: str, size: int):
                if re.search(r"[\uac00-\ud7af]", txt) and _os.path.exists(KOREAN_FONT):
                    return ImageFont.truetype(KOREAN_FONT, size)
                return ImageFont.truetype(FONT_REG, size)

            def compose(sm: int, ss: int, n: str, r: str):
                fm = pick_font(n, sm)
                fs = ImageFont.truetype(FONT_REG, ss)
                parts = [(label, fm, (*dim, 250)), (f"《{n}》", fm, name_color), (f"· {r}", fs, (*dim, 245))]
                total = sum(draw.textlength(t, font=ft) for t, ft, _ in parts) + 14 * (len(parts) - 1)
                return parts, total

            parts, total = compose(22, 18, name, reason)
            if total > max_w:
                parts, total = compose(20, 16, name, reason)
            if total > max_w and len(reason) > 8:
                reason = reason[:8] + "…"
                parts, total = compose(20, 16, name, reason)
            if total > max_w and len(name) > 12:
                name = name[:12] + "…"
                parts, total = compose(18, 15, name, reason)
            if total > max_w and len(name) > 8:
                name = name[:8] + "…"
                parts, total = compose(18, 15, name, "")
            if total > max_w:
                parts, total = compose(16, 14, name[:6] + "…", "")
            cx = 48
            for txt, ft, color in parts:
                draw.text((cx, y_base), txt, font=ft, fill=color, anchor="ls",
                          stroke_width=1, stroke_fill=(0, 0, 0))
                cx += draw.textlength(txt, font=ft) + 14

        y += 46
        g_name, g_reason = game or random.choice(GAMES)
        draw_row("今天适合玩", g_name, g_reason, y + 18)

        y += 44
        if gal:
            gal_name, gal_reason = gal
            draw_row("GAL推荐", gal_name, gal_reason, y + 18, name_color=(255, 214, 232))
        else:
            draw_row("GAL推荐", "暂无数据", "kungal 拉取失败", y + 18, name_color=(255, 214, 232))

        draw.text((48, H - 30), "插画：随机壁纸", font=f_small, fill=(*dim, 200))
        draw.text((W - 48, H - 30), "仅供娱乐 · 鲸鱼娘", font=f_small, fill=(*dim, 200), anchor="ra")

        path = OUT_DIR / f"fortune_{int(time.time() * 1000)}.png"
        canvas.save(path, "PNG")
        return path

    # ---------------------------------------------------------------- 命令
    @filter.command("运势卡", alias={"今日运势", "jrys"})
    async def fortune_card_cmd(self, event: AstrMessageEvent, arg: str = ""):
        name = str(arg or "").strip() or "你"
        try:
            name = event.get_sender_name() or name
        except Exception:  # noqa: BLE001
            pass
        if str(arg or "").strip():
            name = str(arg).strip()
        grade = self._pick_grade()
        wall = await self._wallpaper()
        game = self._fast_game()
        gal = self._fast_gal()
        need_fill = game is None or gal is None
        path = await asyncio.to_thread(self._render, wall, grade, name, game, gal)
        stars5 = max(1, min(5, round(grade * 5 / 7)))
        text = f"🔮 今日运势 · {TITLES[grade]}\n{'★' * stars5}{'☆' * (5 - stars5)}\n{ADVICE[grade]}"
        yield event.chain_result(MessageChain([Comp.Plain(text), Comp.Image(file=str(path))]))
        if need_fill:
            asyncio.create_task(self._fill_and_send(event, wall, grade, name, game, gal))

    async def _fill_and_send(self, event, wall, grade: int, name: str, game, gal) -> None:
        """后台补齐「今天适合玩 / GAL推荐」，补齐后再发一张完整卡。"""
        try:
            if game is None:
                try:
                    game = await self._pick_game()
                except Exception as exc:  # noqa: BLE001
                    logger.info("[fortune] 后台补游戏失败：%r", exc)
            if gal is None:
                try:
                    gal = await self._pick_galgame()
                except Exception as exc:  # noqa: BLE001
                    logger.info("[fortune] 后台补GAL失败：%r", exc)
            if game is None and gal is None:
                return
            path = await asyncio.to_thread(self._render, wall, grade, name, game, gal)
            tips = []
            if game:
                tips.append(f"🎮 今天适合玩：{game[0]} · {game[1]}")
            if gal:
                tips.append(f"💗 GAL推荐：{gal[0]} · {gal[1]}")
            await event.send(MessageChain([Comp.Plain("补上这两行～\n" + "\n".join(tips)), Comp.Image(file=str(path))]))
        except Exception as exc:  # noqa: BLE001
            logger.info("[fortune] 后台补齐发送失败：%r", exc)

    @filter.command("抽运势")
    async def fortune_draw_cmd(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self.fortune_card_cmd(event, arg):
            yield r

    @filter.command("今日运势卡")
    async def fortune_card_cmd2(self, event: AstrMessageEvent, arg: str = ""):
        async for r in self.fortune_card_cmd(event, arg):
            yield r

    @staticmethod
    def _pick_grade() -> int:
        r = random.random()
        acc = 0.0
        for idx, w in enumerate(WEIGHTS):
            acc += w
            if r <= acc:
                return idx
        return 3

    # ---------------------------------------------------------------- 群聊免唤醒入口
    @filter.regex(r"^(运势卡|抽运势|今日运势卡|今日运势|jrys)(\s+.*)?$")
    async def fortune_group(self, event: AstrMessageEvent):
        """群聊直接发即可触发（RegexFilter 不受 wake_prefix 限制）。"""
        msg = (event.message_str or "").strip()
        head = msg.split()[0] if msg.split() else ""
        rest = msg[len(head):].strip()
        async for r in self.fortune_card_cmd(event, rest):
            yield r
        event.stop_event()
# ---------------------------------------------------------------- 本地持久缓存
# 内存缓存 + 落盘 JSON：重启后直接读本地，不再每次联网抓
_GAME_CACHE: dict[str, tuple[float, object]] = {}
_GAME_TTL = 1800          # 内存新鲜期：30 分钟
_DISK_TTL = 86400         # 磁盘可接受的新鲜度：24 小时（超过才后台刷新）
_CACHE_FILE = Path(__file__).with_name("game_cache.json")


def _cache_load_disk() -> None:
    try:
        if not _CACHE_FILE.exists():
            return
        raw = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        for k, v in (raw or {}).items():
            if isinstance(v, list) and len(v) >= 2:
                ts, val = v[0], v[1]
                _GAME_CACHE[k] = (float(ts), val)
    except Exception as exc:  # noqa: BLE001
        logger.info("[fortune] 本地缓存读取失败：%r", exc)


def _cache_save_disk() -> None:
    try:
        data = {k: [ts, val] for k, (ts, val) in _GAME_CACHE.items()}
        tmp = _CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_CACHE_FILE)
    except Exception as exc:  # noqa: BLE001
        logger.info("[fortune] 本地缓存写入失败：%r", exc)


def _cache_age(key: str) -> float:
    item = _GAME_CACHE.get(key)
    return (time.time() - item[0]) if item else 1e9


def _cache_get(key: str, ttl: float | None = None):
    item = _GAME_CACHE.get(key)
    if not item:
        return None
    ts, val = item
    if time.time() - ts > (ttl if ttl is not None else _GAME_TTL):
        return None
    return val


def _cache_put(key: str, val) -> None:
    _GAME_CACHE[key] = (time.time(), val)
    _cache_save_disk()



