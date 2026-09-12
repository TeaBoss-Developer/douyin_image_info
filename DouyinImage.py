# -*- coding: utf-8 -*-
"""
DouyinImage.py - 抖音图集（图文帖）无水印解析

功能：通过分享链接或帖子 ID，解析抖音图集（aweme_type=68）的
      标题、作者、无水印原图列表、统计信息。

核心机制（与 douyin_vedio_info 同源）：
1. 分享链接 → 帖子 ID（支持 v.douyin.com 短链跟随重定向，识别 /note/{id}）
2. 帖子 ID → 异步详情 API /aweme/v1/web/aweme/detail/?aweme_id={id}
3. 从 aweme_detail.images 提取每张图的 url_list[0]（无水印原图直链）

健壮性：
- Cookie 配置化（config.json，本地保存，不提交仓库）
- 识别 JSVM 风控 / API 空数据，给出明确报错
- 字段全部 .get() 容错，缺字段不崩溃

依赖：requests（pip install requests）

用法：
    import DouyinImage
    info = DouyinImage.get_image_info("分享文案...")
    info = DouyinImage.get_image_info_by_id("7684539877870924495")

    先配置 config.json 里的 cookie（浏览器登录抖音后从开发者工具复制）。
"""
import json
import logging
import os
import re
import sys
import urllib.parse
from typing import Any, Dict, List, Optional, Union

import requests

# ---------- 日志 ----------
logger = logging.getLogger("DouyinImage")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

# ---------- 常量 ----------
DEFAULT_CONFIG = {
    "cookie": "",                      # 浏览器登录抖音后复制（必需，否则被风控）
    "timeout": 15,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "note_page": "https://www.douyin.com/note/{nid}",                # 图集详情页
    "detail_api": "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={nid}&device_platform=webapp&aid=6383&channel=channel_pc_web&pc_client_type=1&version_code=170400&version_name=17.4.0&cookie_enabled=true&screen_width=1707&screen_height=1067&browser_language=zh-CN&browser_platform=Win32&browser_name=Chrome&browser_version=120.0.0.0&browser_online=true&engine_name=Blink&os_name=Windows&os_version=10&cpu_core_num=32&device_memory=32&platform=PC&downlink=10&effective_type=4g&round_trip_time=50&webid={nid}",
}

# JSVM 风控标记
_JSVM_MARKERS = ("_$jsvmprt", "jsvm", "captcha", "verify")


def _load_config(config_path: str = "config.json") -> Dict[str, Any]:
    """加载配置文件，缺失时返回默认配置"""
    cfg = dict(DEFAULT_CONFIG)
    if not os.path.exists(config_path):
        logger.warning("配置文件 %s 不存在，使用默认配置（无 Cookie）", config_path)
        return cfg
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        for k, v in user_cfg.items():
            cfg[k] = v
        return cfg
    except Exception as e:
        logger.error("读取配置失败: %s，使用默认配置", e)
        return cfg


def _is_jsvm_blocked(html_text: str) -> bool:
    """检测页面是否为 JSVM 风控/验证页"""
    if not html_text:
        return False
    low = html_text[:2000]
    return any(m in low for m in _JSVM_MARKERS) and len(html_text) < 150000


# ---------- 数据提取 ----------

def _extract_share_url(text: str) -> Optional[str]:
    """从分享文案中提取 URL"""
    m = re.search(r'https?://[^\s，。；！？<>"\']+', text)
    if not m:
        logger.warning("分享文案中未找到 URL")
        return None
    return m.group(0).rstrip('.,;')


def _extract_note_id_from_url(url: str, timeout: int = 15,
                              user_agent: str = "") -> Optional[str]:
    """
    从分享链接提取帖子 ID：
    1. 优先从 URL 路径匹配 /note/{id} 或 /video/{id}
    2. 短链（v.douyin.com/xxx）跟随重定向后解析
    """
    m = re.search(r'(?:note|video|share/video)/(\d{15,})', url)
    if m:
        return m.group(1)

    headers = {"User-Agent": user_agent or DEFAULT_CONFIG["user_agent"]}
    try:
        resp = requests.get(url, headers=headers, allow_redirects=True, timeout=timeout)
        final_url = resp.url or url
        m2 = re.search(r'(?:note|video|share/video)/(\d{15,})', final_url)
        if m2:
            return m2.group(1)
        for h in resp.history:
            loc = h.headers.get("Location", "")
            m3 = re.search(r'(?:note|video|share/video)/(\d{15,})', loc)
            if m3:
                return m3.group(1)
        # 兜底：URL 里任意 19 位数字
        m4 = re.search(r'\b(\d{19})\b', final_url)
        if m4:
            return m4.group(1)
        logger.warning("重定向后未找到帖子 ID: %s", final_url)
        return None
    except Exception as e:
        logger.warning("短链解析失败: %s", e)
        return None


# ---------- API 通道 ----------

def _fetch_detail_api(note_id: str, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """主通道：调用异步详情 API，返回 aweme_detail dict"""
    api_tpl = config.get("detail_api", DEFAULT_CONFIG["detail_api"])
    url = api_tpl.format(nid=note_id)
    headers = {
        "User-Agent": config.get("user_agent", DEFAULT_CONFIG["user_agent"]),
        "Referer": config.get("note_page", DEFAULT_CONFIG["note_page"]).format(nid=note_id),
        "Accept": "application/json, text/plain, */*",
        "Cookie": config.get("cookie", ""),
    }
    try:
        resp = requests.get(url, headers=headers, timeout=int(config.get("timeout", 15)))
        if resp.status_code != 200:
            logger.warning("详情 API 请求失败 status=%s", resp.status_code)
            return None
        try:
            data = resp.json()
        except Exception:
            logger.warning("详情 API 返回非 JSON")
            return None
        if data.get("status_code") not in (0, None):
            logger.warning("详情 API 被风控（status_code=%s）", data.get("status_code"))
            return None
        ad = data.get("aweme_detail") or {}
        if not ad:
            logger.warning("详情 API 无 aweme_detail 数据")
            return None
        return ad
    except Exception as e:
        logger.warning("详情 API 请求异常: %s", e)
        return None


# ---------- 字段提取 ----------

def _normalize_url(u: Any) -> str:
    """把 url 字段规范为完整 https 地址"""
    if not u:
        return ""
    if isinstance(u, str):
        return u if u.startswith("http") else "https:" + u
    if isinstance(u, list):
        if not u:
            return ""
        return _normalize_url(u[0])
    if isinstance(u, dict):
        ul = u.get("url_list") or []
        if ul:
            return _normalize_url(ul[0])
        uri = u.get("uri")
        if uri:
            return "https:" + uri if not uri.startswith("http") else uri
    return ""


def _parse_aweme_detail(ad: Dict[str, Any]) -> Dict[str, Any]:
    """从 aweme_detail 提取图集信息"""
    images_raw = ad.get("images") or []
    images = []
    for img in images_raw:
        if not isinstance(img, dict):
            continue
        images.append({
            "url": _normalize_url(img.get("url_list")),          # 无水印原图
            "download_url": _normalize_url(img.get("download_url_list")),  # 带水印
            "width": img.get("width", 0),
            "height": img.get("height", 0),
        })

    stats = ad.get("statistics") or {}
    author = ad.get("author") or {}
    music = ad.get("music") or {}

    return {
        "title": ad.get("desc", ""),
        "note_id": ad.get("aweme_id", ""),
        "author": author.get("nickname", ""),
        "user_id": ad.get("author_user_id") or str(author.get("uid", "")),
        "image_count": len(images),
        "images": images,                     # 无水印原图列表
        "bg_music": _normalize_url(music.get("play_url")),
        "create_time": ad.get("create_time", 0),
        "like_count": stats.get("digg_count", 0),
        "share_count": stats.get("share_count", 0),
        "love_count": stats.get("collect_count", 0),
        "comment_count": stats.get("comment_count", 0),
    }


# ---------- 对外 API ----------

def get_image_info_by_id(note_id: str,
                         config: Optional[Union[str, Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """
    通过帖子 ID 解析图集信息。

    :param note_id: 帖子 ID（19 位数字）
    :param config: 配置 dict 或路径；None 时加载 ./config.json
    :return: dict / None（失败）
    """
    if isinstance(config, str) or config is None:
        cfg = _load_config(config if isinstance(config, str) else "config.json")
    else:
        cfg = config

    if not note_id or not re.fullmatch(r"\d{15,}", str(note_id)):
        logger.error("无效的帖子 ID: %s", note_id)
        return None

    if not cfg.get("cookie"):
        logger.warning("config.json 未配置 cookie！抖音风控会拦截请求，请先填入浏览器 Cookie")

    ad = _fetch_detail_api(note_id, cfg)
    if ad is None:
        logger.error("详情 API 解析失败（图集 %s），请检查 Cookie 是否有效", note_id)
        return None

    images = ad.get("images")
    if not images:
        logger.error("该帖子不是图集（aweme_type=%s，无 images 字段）", ad.get("aweme_type"))
        return None

    logger.info("图集解析成功: %s（%d 张图）", note_id, len(images))
    return _parse_aweme_detail(ad)


def get_image_info(share_text: str,
                   config: Optional[Union[str, Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """
    通过分享文案解析图集信息（对外主方法）。

    :param share_text: 抖音分享文案
    :param config: 配置 dict 或路径；None 时加载 ./config.json
    :return: dict / None（失败）
    """
    url = _extract_share_url(share_text)
    if not url:
        return None

    if isinstance(config, str) or config is None:
        cfg = _load_config(config if isinstance(config, str) else "config.json")
    else:
        cfg = config

    note_id = _extract_note_id_from_url(url,
                                        timeout=int(cfg.get("timeout", 15)),
                                        user_agent=cfg.get("user_agent", ""))
    if not note_id:
        logger.error("未能从分享链接提取帖子 ID: %s", url)
        return None

    return get_image_info_by_id(note_id, cfg)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if re.fullmatch(r"\d{15,}", arg):
        result = get_image_info_by_id(arg)
    else:
        result = get_image_info(arg)
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("解析失败")
        sys.exit(1)
