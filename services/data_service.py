import asyncio
import aiohttp
from aiohttp import TCPConnector, ClientTimeout
from typing import Dict, Any, Optional
import random
import logging
import time  # 🔧 新增：用于时间戳防缓存
from config import settings
from utils.retry import retry
from curl_cffi.requests import AsyncSession as CffiSession  # 🔧 新增：绕过风控


class DataService:
    _instance: Optional["DataService"] = None
    _session: Optional[aiohttp.ClientSession] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    async def init_session(cls):
        if cls._session is None or cls._session.closed:
            connector = TCPConnector(limit=settings.CONCURRENT_LIMIT, ssl=False)
            cls._session = aiohttp.ClientSession(connector=connector,
                                                 timeout=ClientTimeout(total=settings.HTTP_TIMEOUT))

    @classmethod
    async def close_session(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()

    @staticmethod
    def _build_headers(referer_url: str) -> Dict[str, str]:
        ua_pool = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        ]
        headers = {
            "User-Agent": random.choice(ua_pool), "Referer": referer_url,
            "Origin": "https://www.bilibili.com", "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9", "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-site",
        }
        cookie = settings.build_cookie_str()
        if cookie:
            headers["Cookie"] = cookie
        return headers

    @retry(max_attempts=settings.MAX_RETRIES, delay=2.0)
    async def fetch_json(self, url: str, params: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        async with self._session.get(url, params=params, headers=headers) as resp:
            ct = resp.headers.get("Content-Type", "")
            if resp.status == 412 or "text/html" in ct:
                text = await resp.text()
                if "安全风控" in text or resp.status == 412:
                    raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=412,
                                                      message="B站风控拦截")
            resp.raise_for_status()
            return await resp.json()

    async def fetch_video_stats(self, bvid: str) -> Dict[str, str]:
        default = {"view": "N/A", "danmaku": "N/A", "like": "N/A", "coin": "N/A",
                   "favorite": "N/A", "share": "N/A", "reply": "N/A"}
        try:
            data = await self.fetch_json(
                "https://api.bilibili.com/x/web-interface/view",
                {"bvid": bvid},
                self._build_headers(f"https://www.bilibili.com/video/{bvid}")
            )
            if data.get("code") == 0:
                stat = data.get("data", {}).get("stat", {})
                return {k: str(stat.get(k, "N/A")) for k in default}
            return default
        except Exception as e:
            if "412" in str(e): raise
            logging.debug(f"获取视频 {bvid} 详情失败: {e}")
            return default

    async def fetch_follower_count(self, uid: str, cache: Dict[str, Any]) -> str:
        if not uid or uid == "N/A": return "N/A"
        if uid in cache: return cache[uid]
        try:
            data = await self.fetch_json(
                "https://api.bilibili.com/x/relation/stat",
                {"vmid": uid},
                self._build_headers(f"https://space.bilibili.com/{uid}")
            )
            if data.get("code") == 0:
                follower = data.get("data", {}).get("follower")
                result = str(follower) if follower is not None else "字段缺失"
            else:
                result = f"接口错误({data.get('code')})"
            cache[uid] = result
            return result
        except Exception as e:
            if "412" in str(e): raise
            logging.debug(f"获取用户 {uid} 粉丝数失败: {e}")
            cache[uid] = "请求失败"
            return "请求失败"

    async def fetch_video_tags(self, bvid: str) -> str:
        """获取视频标签 - curl_cffi 强化版（绕过B站WAF）"""
        import time
        from curl_cffi.requests import AsyncSession  # ✅ 确认 curl_cffi >= 0.5.0

        try:
            # 🎯 关键1: Referer 必须带时间戳 + 完整视频路径
            referer = f"https://www.bilibili.com/video/{bvid}?t={int(time.time())}&spm_id_from=333.1007.tianma"

            # 🎯 关键2: 构建完整浏览器指纹（缺一不可）
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Referer": referer,
                "Origin": "https://www.bilibili.com",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                # 🔥 Sec-Ch-Ua 系列（B站WAF必校验）
                "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "Sec-Ch-Ua-Arch": '"x86"',
                "Sec-Ch-Ua-Bitness": '"64"',
                "Sec-Ch-Ua-Full-Version": '"124.0.6367.118"',
                "Sec-Ch-Ua-Model": '""',
                "Sec-Ch-Ua-WoW64": "?0",
            }

            # 🎯 关键3: 添加Cookie（从settings读取）
            cookie_str = settings.build_cookie_str()
            if cookie_str:
                headers["Cookie"] = cookie_str

            # 🎯 关键4: 使用最新chrome124指纹 + 严格超时
            async with AsyncSession(impersonate="chrome124", timeout=settings.HTTP_TIMEOUT) as session:
                # 🎯 关键5: 请求前强制延迟（避免并发触发风控）
                await asyncio.sleep(0.8)

                resp = await session.get(
                    "https://api.bilibili.com/x/tag/archive/tags",
                    params={"bvid": bvid, "jsonp": "jsonp", "_": str(int(time.time() * 1000))},
                    headers=headers
                )

                # 🎯 关键6: 检查响应
                if resp.status_code != 200:
                    logging.warning(f"标签接口返回 {resp.status_code}")
                    return "获取失败"

                data = resp.json()
                if data.get("code") == 0 and isinstance(data.get("data"), list):
                    tags = [t.get("tag_name") for t in data["data"] if t.get("tag_name")]
                    return ", ".join(tags) if tags else "无标签"
                return "无标签"

        except Exception as e:
            if "412" in str(e) or "banned" in str(e).lower():
                logging.warning(f"🔒 标签接口仍被风控: {e}")
            else:
                logging.debug(f"获取标签异常: {e}")
            return "获取失败"
