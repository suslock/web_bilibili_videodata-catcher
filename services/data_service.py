import aiohttp
from aiohttp import TCPConnector, ClientTimeout
from typing import Dict, Any, Optional
import random
import logging
from config import settings  # 从项目根目录导入
from utils.retry import retry  # 从项目根目录导入


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
        default = {"view": "N/A",
                   "danmaku": "N/A",
                   "like": "N/A",
                   "coin": "N/A",
                   "favorite": "N/A",
                   "share": "N/A",
                   "reply": "N/A"}
        try:
            data = await self.fetch_json(
                "https://api.bilibili.com/x/web-interface/view",
                {"bvid": bvid},
                self._build_headers(f"https://www.bilibili.com/video/{bvid}")
            )
            if data.get("code") == 0:
                stat = data.get("data", {}).get("stat", {})
                # 返回所有统计字段，包括新增的 danmaku
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