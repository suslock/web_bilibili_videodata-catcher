import os
from typing import Dict, Tuple, List


class Settings:
    """集中配置管理（使用普通类避免 dataclass 可变默认值报错）"""

    # 🔍 搜索配置
    KEYWORD: str = os.getenv("BILI_KEYWORD", "hhh")
    BASE_FILENAME: str = "Bilibili"
    MAX_PAGES: int = int(os.getenv("BILI_MAX_PAGES", "10"))
    REQUEST_DELAY: float = float(os.getenv("BILI_REQUEST_DELAY", "2.0"))

    #TODO 🔐 Cookie配置,需注意涉及隐私信息，请勿泄露信息
    SESSDATA: str = os.getenv("BILI_SESSDATA", "9f6eb7ba%2C1792754296%2Cb9876%2A41CjC3u_dam_vBNAYQG3x7a7evh1inMjbLBUtOa2WOx2hyhUbtK-EB9SlcAMdsrm9WVCwSVnp1MHFTc3d6OE5KVUpzM2ZydHo1YkgzcURZVzd4elV1UjVnb19ZeXRVMXNGYy05TjRRenhjUkwzMDBMdWhaS2tZMFRJNEhGSVhRMzNSX003X25IeENBIIEC")
    BILI_JCT: str = os.getenv("BILI_BILI_JCT", "6fdbff4b2dfde4bee319ec74ca831383")
    BUVID3: str = os.getenv("BILI_BUVID3", "7E792CA1-A32A-57DA-764D-A3B6D63A51A866151infoc")
    DEDE_USERID: str = os.getenv("BILI_DEDE_USERID", "")

    # 🌐 网络配置
    HTTP_TIMEOUT: int = 30
    MAX_RETRIES: int = 3
    CONCURRENT_LIMIT: int = 2

    # 📊 排序选项
    SORT_OPTIONS: Dict[str, Tuple[str, str]] = {
        "totalrank": ("totalrank", "综合排序"),
        "click": ("click", "最多播放"),
        "pubdate": ("pubdate", "最新发布"),
        "dm": ("dm", "最多弹幕"),
        "stow": ("stow", "最多收藏"),
    }

    # 📅 日期选项
    DATE_RANGE_OPTIONS: Dict[str, Tuple[int, str]] = {
        "0": (0, "全部时间"),
        "1": (1, "最近1天"),
        "7": (7, "最近7天"),
    }

    # 📋 Excel表头
    HEADERS: List[str] = [
        "作品标题", "UP主", "UP主UID", "粉丝数", "发布时间",
        "播放量", "弹幕数","点赞数", "投币数", "收藏数", "转发数", "评论数", "BV号","视频标签"
    ]

    @classmethod
    def build_cookie_str(cls) -> str:
        cookies = {"SESSDATA": cls.SESSDATA, "bili_jct": cls.BILI_JCT,
                   "buvid3": cls.BUVID3, "DedeUserID": cls.DEDE_USERID}
        return "; ".join(f"{k}={v}" for k, v in cookies.items() if v and v.strip())

    @classmethod
    def mask_sensitive(cls, text: str, visible: int = 4) -> str:
        if not text or len(text) <= visible:
            return "*" * len(text) if text else ""
        return text[:visible] + "*" * (len(text) - visible)

    @classmethod
    def validate_cookies(cls) -> bool:
        return bool(cls.SESSDATA and cls.BILI_JCT)


# 全局配置实例
settings = Settings()
