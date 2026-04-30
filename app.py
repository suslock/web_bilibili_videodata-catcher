from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uuid
import asyncio
import logging
import re
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import quote

from config import settings
from utils.logger import setup_logging
from services.data_service import DataService
from services.search_service import SearchService
from services.export_service import ExportService

# 初始化日志
setup_logging()
logger = logging.getLogger(__name__)

# FastAPI应用
app = FastAPI(title="B站视频数据爬取工具", version="2.0")

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件和模板
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# 全局任务存储
active_tasks = {}


class SearchRequest(BaseModel):
    keyword: str
    max_pages: int = 10
    date_range: str = "1"  # "1" or "7"
    sort_type: str = "totalrank"  # 排序类型


class TaskStatus(BaseModel):
    status: str
    progress: int
    current_page: int = 0
    total_pages: int = 0
    message: str = ""
    data_preview: Optional[list] = None
    error: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页"""
    return templates.TemplateResponse(
        name="index.html",
        context={"request": request},
        request=request
    )


@app.post("/api/search")
async def start_search(req: SearchRequest):
    """开始搜索任务"""
    task_id = f"task_{uuid.uuid4().hex[:8]}"

    # 验证配置
    if not settings.validate_cookies():
        raise HTTPException(status_code=400, detail="Cookie未配置，请设置环境变量")

    # 验证参数
    if not req.keyword or len(req.keyword.strip()) == 0:
        raise HTTPException(status_code=400, detail="搜索关键词不能为空")

    if req.max_pages < 1 or req.max_pages > 50:
        raise HTTPException(status_code=400, detail="页数必须在1-50之间")

    # === 1. 生成自定义文件名 ===
    today = datetime.now()
    date_str = ""
    days = int(req.date_range)

    # TODO: [文件名生成] 根据时间范围生成不同的后缀
    if days == 0:
        # 全部时间
        date_str = "全部时间"
    elif days == 1:
        # 如果只看最近一天，时间就是当天年月日
        date_str = today.strftime("%Y%m%d")
    else:
        # 如果是最近七天（或其他），格式为：七天前年月日 - 当天年月日
        start_date = today - timedelta(days=days)
        date_str = f"{start_date.strftime('%Y%m%d')}-{today.strftime('%Y%m%d')}"

    # 处理关键词：移除非法字符，空格变下划线
    safe_kw = re.sub(r'[\\/*?:"<>|]', '', req.keyword).strip()
    safe_kw = re.sub(r'\s+', '_', safe_kw)
    if len(safe_kw) > 20:
        safe_kw = safe_kw[:20]

    # 注意：文件名中如果包含中文“全部时间”，之前的 RFC 5987 编码逻辑已经能很好地处理下载问题
    filename = f"BILIBILI_{safe_kw}_{date_str}.xlsx"
    # ===============================

    # 2. 创建任务，将文件名存入字典
    active_tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "current_page": 0,
        "total_pages": req.max_pages,
        "message": "任务已创建，等待开始...",
        "data": None,
        "excel": None,
        "error": None,
        "filename": filename,  # ✅ 关键：保存文件名以便下载时使用
        "keyword": req.keyword,
        "date_range": req.date_range
    }

    # 异步执行任务
    asyncio.create_task(run_search_task(task_id, req))

    return {"task_id": task_id, "message": "任务已启动", "filename": filename}


async def run_search_task(task_id: str, req: SearchRequest):
    """执行搜索任务"""
    try:
        active_tasks[task_id]["status"] = "running"
        active_tasks[task_id]["message"] = "正在初始化..."

        # 初始化服务
        await DataService.init_session()

        # 进度回调
        def progress_callback(current: int, total: int, msg: str):
            active_tasks[task_id]["current_page"] = current
            active_tasks[task_id]["progress"] = int((current / total) * 100)
            active_tasks[task_id]["message"] = msg

        # 创建搜索服务
        search_svc = SearchService(progress_callback=progress_callback)

        # 获取天数
        max_days = int(req.date_range)

        # 执行搜索
        active_tasks[task_id]["message"] = "开始抓取数据..."
        data = await search_svc.search_and_fetch(
            keyword=req.keyword,
            max_pages=req.max_pages,
            max_days=max_days,
            order_param=req.sort_type,
            progress_callback=progress_callback
        )

        # 导出Excel
        # made by github-suslock
        if data:
            active_tasks[task_id]["message"] = "正在生成Excel..."
            export_svc = ExportService()
            excel_bytes = export_svc.save_to_excel_bytes(data)

            # 存储数据和Excel
            active_tasks[task_id]["data"] = data
            active_tasks[task_id]["excel"] = excel_bytes
            active_tasks[task_id]["data_preview"] = data[:10]  # 预览前10条
            active_tasks[task_id]["status"] = "completed"
            active_tasks[task_id]["progress"] = 100
            active_tasks[task_id]["message"] = f"抓取完成！共 {len(data)} 条数据"

            logger.info(f"任务 {task_id} 完成，共 {len(data)} 条数据，文件名: {active_tasks[task_id].get('filename')}")
        else:
            active_tasks[task_id]["status"] = "completed"
            active_tasks[task_id]["message"] = "未找到符合条件的数据"
            active_tasks[task_id]["progress"] = 100

    except Exception as e:
        error_msg = str(e)
        if "412" in error_msg or "风控" in error_msg:
            error_msg = "触发B站风控，请稍后重试或检查Cookie是否有效"

        active_tasks[task_id]["status"] = "failed"
        active_tasks[task_id]["error"] = error_msg
        active_tasks[task_id]["message"] = f"任务失败: {error_msg}"

        logger.error(f"任务 {task_id} 失败: {error_msg}", exc_info=True)

    finally:
        await DataService.close_session()


@app.get("/api/task/{task_id}")
async def get_task_status(task_id: str):
    """获取任务状态"""
    if task_id not in active_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    task = active_tasks[task_id]
    return {
        "task_id": task_id,
        "status": task["status"],
        "progress": task["progress"],
        "current_page": task["current_page"],
        "total_pages": task["total_pages"],
        "message": task["message"],
        "data_preview": task.get("data_preview"),
        "error": task.get("error"),
        "filename": task.get("filename")  # ✅ 返回文件名给前端
    }


@app.get("/api/download/{task_id}")
async def download_excel(task_id: str):
    """下载Excel文件"""
    if task_id not in active_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = active_tasks[task_id]

    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"任务未完成，当前状态: {task['status']}")

    if "excel" not in task or task["excel"] is None:
        raise HTTPException(status_code=400, detail="任务无Excel数据")

    # 获取任务生成时保存的自定义文件名
    original_filename = task.get("filename", "Bilibili_data.xlsx")

    # 确保文件名以.xlsx结尾
    if not original_filename.endswith(".xlsx"):
        original_filename = original_filename + ".xlsx"

    # 🔧 修复：正确编码中文文件名 (RFC 5987标准)
    # 1. 生成ASCII兼容的备选文件名（移除中文，保留英文/数字/下划线）
    ascii_filename = re.sub(r'[^\x00-\x7F]', '_', original_filename)

    # 2. URL编码UTF-8文件名（用于filename*参数）
    encoded_filename = quote(original_filename.encode('utf-8'))

    # 3. 构建符合RFC 5987的Content-Disposition头
    # 格式: attachment; filename="ascii_fallback"; filename*=UTF-8''encoded_name
    content_disposition = f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}'

    logger.info(f"下载文件: {original_filename} (ASCII: {ascii_filename}), 大小: {len(task['excel'])} bytes")

    return Response(
        content=task["excel"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            # ✅ 关键修复：使用RFC 5987标准兼容中文文件名
            "Content-Disposition": content_disposition,
            # 添加缓存控制，防止浏览器缓存旧文件
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


@app.get("/api/config/check")
async def check_config():
    """检查配置"""
    return {
        "cookies_configured": settings.validate_cookies(),
        "sessdata_masked": settings.mask_sensitive(settings.SESSDATA) if settings.SESSDATA else ""
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)