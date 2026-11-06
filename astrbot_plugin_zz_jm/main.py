"""JM 漫画下载 → PDF（鲸鱼娘自研）"""

from __future__ import annotations

import asyncio
import glob
import os
import re
import time
from pathlib import Path

import jmcomic
from PIL import Image

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import File as FileComp
from astrbot.core.message.message_event_result import MessageChain

PROXY = "http://127.0.0.1:7890"
BASE = Path(r"D:\DSK\BOT\runtime\jm")


@register("zz_jm", "鲸鱼娘", "JM 漫画下载 → PDF", "1.0.0")
class ZzJmPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self._config = config

    # ---------------------------------------------------------------- 配置
    def _opt(self, key: str, default):
        cfg = self._config
        if cfg is None:
            return default
        try:
            val = cfg.get(key, default)
        except Exception:  # noqa: BLE001
            return default
        return default if val in (None, "") else val

    def _work_dir(self) -> Path:
        d = Path(str(self._opt("work_dir", str(BASE))))
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _jm_option(self, base_dir: Path):
        proxy = str(self._opt("proxy", PROXY)) or ""
        cfg = {
            "dir_rule": {"base_dir": str(base_dir).replace("\\", "/"), "rule": "Bd_Aid_Pname"},
            "download": {
                "image": {"decode": True, "suffix": ".jpg"},
                "threading": {"image": int(self._opt("threads", 16))},
            },
            "client": {
                "retry_times": 3,
                "postman": {
                    "meta_data": {
                        "impersonate": "chrome",
                        "proxies": {"http": proxy, "https": proxy},
                    }
                },
            },
        }
        return jmcomic.JmOption.construct(cfg)

    # ---------------------------------------------------------------- 下载
    @staticmethod
    def _images_to_pdf(images: list[Path], pdf_path: Path) -> int:
        pages = []
        for p in images:
            try:
                im = Image.open(p)
                if im.mode in ("RGBA", "P", "L"):
                    im = im.convert("RGB")
                elif im.mode != "RGB":
                    im = im.convert("RGB")
                pages.append(im.copy())
                im.close()
            except Exception:  # noqa: BLE001
                continue
        if not pages:
            raise RuntimeError("没有可用的图片")
        first, rest = pages[0], pages[1:]
        first.save(pdf_path, "PDF", save_all=True, append_images=rest, resolution=100.0)
        return len(pages)

    def _download(self, album_id: str) -> tuple[Path, int, int]:
        work = self._work_dir()
        opt = self._jm_option(work)
        album = jmcomic.download_album(album_id, opt)

        # 目录定位：Bd_Aid_Pname 规则下是 work/{album_id}/章节名/
        candidates = [work / str(album_id), work / f"JM{album_id}"]
        raw = next((c for c in candidates if c.is_dir()), None)
        if raw is None:
            raw = next((d for d in work.iterdir() if d.is_dir() and str(album_id) in d.name), None)
        if raw is None:
            raw = work

        images = sorted(
            [Path(p) for p in glob.glob(str(raw / "**" / "*.jpg"), recursive=True)]
            + [Path(p) for p in glob.glob(str(raw / "**" / "*.png"), recursive=True)]
            + [Path(p) for p in glob.glob(str(raw / "**" / "*.webp"), recursive=True)]
        )
        if not images:
            raise RuntimeError(f"本子 {album_id} 没下到图片（ID 可能不存在，或站点抽风）")

        pdf = work / f"JM{album_id}.pdf"
        pages = self._images_to_pdf(images, pdf)
        for img in images:
            try:
                img.unlink()
            except Exception:  # noqa: BLE001
                pass
        for d in sorted({img.parent for img in images}, key=lambda x: len(str(x)), reverse=True):
            try:
                d.rmdir()
            except Exception:  # noqa: BLE001
                pass
        try:
            raw.rmdir()
        except Exception:  # noqa: BLE001
            pass
        return pdf, pages, pdf.stat().st_size

    def _cleanup(self) -> None:
        keep_days = int(self._opt("keep_days", 3))
        deadline = time.time() - keep_days * 86400
        for f in glob.glob(str(self._work_dir() / "JM*.pdf")):
            try:
                if os.path.getmtime(f) < deadline:
                    os.remove(f)
            except Exception:  # noqa: BLE001
                continue

    # ---------------------------------------------------------------- 命令
    @filter.command("jm")
    async def jm_cmd(self, event: AstrMessageEvent, arg: str = ""):
        """jm 350234 —— 下载并转成 PDF"""
        text = (arg or "").strip() or (event.message_str or "")
        m = re.search(r"(\d{3,8})", text)
        if not m:
            yield event.plain_result("用法：jm 350234（漫画 ID）")
            return
        album_id = m.group(1)
        yield event.plain_result(f"收到 JM{album_id}，开始下载，页多的话要等一会儿。")
        try:
            pdf, pages, size = await asyncio.to_thread(self._download, album_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[jm] 下载失败 %s: %r", album_id, exc)
            yield event.plain_result(f"JM{album_id} 下载失败：{str(exc)[:80]}")
            return
        mb = size / 1024 / 1024
        try:
            yield event.chain_result(
                [FileComp(name=f"{album_id}.pdf", file=str(pdf))]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[jm] 发送文件失败: %r", exc)
            yield event.plain_result(f"文件发送失败：{str(exc)[:80]}")
        yield event.plain_result(f"JM{album_id} · {pages} 页 · PDF {mb:.1f}MB")
        self._cleanup()

    @filter.regex(r"^[Jj][Mm]\s?\d{3,8}$")
    async def jm_short(self, event: AstrMessageEvent):
        """直接发 JM350234 也触发"""
        text = (event.message_str or "").strip()
        m = re.search(r"(\d{3,8})", text)
        if not m:
            return
        album_id = m.group(1)
        yield event.plain_result(f"收到 JM{album_id}，开始下载，页多的话要等一会儿。")
        try:
            pdf, pages, size = await asyncio.to_thread(self._download, album_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[jm] 下载失败 %s: %r", album_id, exc)
            yield event.plain_result(f"JM{album_id} 下载失败：{str(exc)[:80]}")
            return
        mb = size / 1024 / 1024
        try:
            yield event.chain_result([FileComp(name=f"{album_id}.pdf", file=str(pdf))])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[jm] 发送文件失败: %r", exc)
            yield event.plain_result(f"文件发送失败：{str(exc)[:80]}")
        yield event.plain_result(f"JM{album_id} · {pages} 页 · PDF {mb:.1f}MB")
        self._cleanup()

    # ---------------------------------------------------------------- 群聊免唤醒入口
    @filter.regex(r"^(?i:jm)\s*\d{3,8}$")
    async def jm_group(self, event: AstrMessageEvent):
        """群聊直接发即可触发（RegexFilter 不受 wake_prefix 限制）。"""
        msg = (event.message_str or "").strip()
        head = msg.split()[0] if msg.split() else ""
        rest = msg[len(head):].strip()
        async for r in self.jm_cmd(event, rest):
            yield r
        event.stop_event()
