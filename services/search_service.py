import asyncio
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Callable
from services.data_service import DataService
from config import settings


class SearchService:
    """搜索抓取服务"""

    def __init__(self, progress_callback: Optional[Callable] = None):
        self.data_service = DataService()
        self.follower_cache: Dict[str, Any] = {}
        self.seen_bvids: set = set()
        self.progress_callback = progress_callback
        self.semaphore = asyncio.Semaphore(3)  # 限制并发，减少风控

    def _calculate_time_range(self, max_days: int) -> tuple:
        """计算时间戳范围"""
        now = datetime.now(timezone(timedelta(hours=8)))

        # TODO: [核心逻辑] 处理“全部时间”的情况
        if max_days == 0:
            # B站成立于2009年，这里设置为2009-06-26 00:00:00
            start_dt = datetime(2009, 6, 26, 0, 0, 0, tzinfo=timezone(timedelta(hours=8)))
            end_dt = now
            logging.info("📅 时间范围: 全部时间 (2009-06-26 ~ Now)")
            return int(start_dt.timestamp()), int(end_dt.timestamp())

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if max_days == 1:
            start_dt = today_start
        else:
            start_dt = today_start - timedelta(days=max_days - 1)

        end_dt = now  # 使用当前时间，避免漏掉最新视频

        logging.info(f"📅 时间范围: {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d %H:%M')}")
        return int(start_dt.timestamp()), int(end_dt.timestamp())

    def _clean_title(self, text: str) -> str:
        """清理标题HTML标签"""
        if not isinstance(text, str):
            return "N/A"
        return re.sub(r'<[^>]+>', '', text)

    def _parse_video_item(self, item: Dict[str, Any]) -> Optional[List[str]]:
        """解析单个视频项"""
        title = self._clean_title(item.get("title", "N/A"))
        author = item.get("author", "N/A") or item.get("upic", {}).get("name", "N/A")
        uid = str(item.get("mid", "N/A"))
        bvid = item.get("bvid", "N/A")

        # 去重
        if bvid in self.seen_bvids:
            return None
        self.seen_bvids.add(bvid)

        # 解析发布时间
        pubdate_ts = item.get("pubdate") or item.get("created") or item.get("ctime") or 0
        pubdate = "未知"
        if pubdate_ts:
            try:
                pub_date = datetime.fromtimestamp(pubdate_ts, tz=timezone(timedelta(hours=8)))
                pubdate = pub_date.strftime('%Y-%m-%d %H:%M')
            except Exception:
                pass

        return [title, author, uid, None, pubdate, None, None, None, None, None, None, bvid]

    async def fetch_page(self, keyword: str, page: int, order_param: str,
                         pubtime_begin_s: int, pubtime_end_s: int) -> Optional[List[Dict]]:
        """抓取单页搜索结果"""
        url = "https://api.bilibili.com/x/web-interface/search/type"
        params = {
            "search_type": "video",
            "keyword": keyword,
            "page": page,
            "order": order_param,
            "pubtime_begin_s": pubtime_begin_s,
            "pubtime_end_s": pubtime_end_s,
            "pagesize": 20,  # 降低每页数量，减少风控
            "duration": "",
            "tids": 0,
        }
        headers = DataService._build_headers(f"https://search.bilibili.com/all?keyword={keyword}")

        try:
            result = await self.data_service.fetch_json(url, params, headers)
            if result.get("code") != 0:
                logging.error(f"搜索接口错误: {result.get('message')}")
                return None
            return result.get("data", {}).get("result", [])
        except Exception as e:
            logging.error(f"抓取第 {page} 页失败: {e}")
            return None

    async def _enrich_video_data(self, base_row: List[str], bvid: str, uid: str) -> Optional[List[str]]:
        """补充视频数据（带信号量控制）"""
        async with self.semaphore:
            try:
                video_stats, follower_count = await asyncio.gather(
                    self.data_service.fetch_video_stats(bvid),
                    self.data_service.fetch_follower_count(uid, self.follower_cache)
                )

                return [
                    base_row[0],  # 标题
                    base_row[1],  # UP主
                    base_row[2],  # UID
                    str(follower_count),  # 粉丝数
                    base_row[4],  # 发布时间
                    str(video_stats["view"]),
                    str(video_stats["danmaku"]),
                    str(video_stats["like"]),
                    str(video_stats["coin"]),
                    str(video_stats["favorite"]),
                    str(video_stats["share"]),
                    str(video_stats["reply"]),
                    base_row[-1],  # BV号
                ]
            except Exception as e:
                if "412" in str(e):
                    raise
                logging.debug(f" enrich {bvid} 失败: {e}")
                return None

    async def search_and_fetch(self, keyword: str, max_pages: int, max_days: int,
                               order_param: str, progress_callback: Optional[Callable] = None) -> List[List[str]]:
        """主抓取流程"""
        all_data = []
        pubtime_begin_s, pubtime_end_s = self._calculate_time_range(max_days)

        logging.info(f"📅 时间范围: {datetime.fromtimestamp(pubtime_begin_s).strftime('%Y-%m-%d')} ~ "
                     f"{datetime.fromtimestamp(pubtime_end_s).strftime('%Y-%m-%d %H:%M')}")

        for page in range(1, max_pages + 1):
            logging.info(f"🔍 抓取第 {page}/{max_pages} 页...")

            if progress_callback:
                progress_callback(page, max_pages, f"正在抓取第 {page} 页...")

            result_list = await self.fetch_page(
                keyword, page, order_param,
                pubtime_begin_s, pubtime_end_s
            )

            if not result_list:
                logging.warning(f"⚠️ 第 {page} 页结果为空")
                break

            # 并发处理本页视频
            tasks = []
            for item in result_list:
                parsed = self._parse_video_item(item)
                if not parsed:
                    continue

                bvid = parsed[-1]
                uid = parsed[2]
                tasks.append(self._enrich_video_data(parsed, bvid, uid))

            # 批量执行
            enriched_list = await asyncio.gather(*tasks, return_exceptions=True)

            # 过滤异常和None
            for result in enriched_list:
                if isinstance(result, list) and result:
                    all_data.append(result)
                elif isinstance(result, Exception) and "412" in str(result):
                    raise result  # 412直接抛出，停止采集

            # 页间延迟（防风控）
            await asyncio.sleep(settings.REQUEST_DELAY)

        logging.info(f"🏁 抓取完成: 共 {len(all_data)} 条有效数据")
        return all_data