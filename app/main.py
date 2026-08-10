from pathlib import Path
from contextlib import asynccontextmanager
import logging
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# 兼容 PyCharm 以脚本路径直接运行 app/main.py 的场景。
# 这种方式默认只把 app/ 加入 sys.path，需要补上项目根目录才能导入 app 包。
if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from app.api import admin_router, chat_router, websocket_router
from app.core.config import PROJECT_ROOT, get_settings
from app.core.logging import configure_logging
from app.db import init_db
from app.demo_data import seed_demo_environment
from app.knowledge.importer import import_knowledge_sources
from app.realtime import realtime_manager
from app.llm.providers import build_llm_fallback_configs
from app.services.sop_followup_scheduler import (
    start_sop_followup_scheduler,
    stop_sop_followup_scheduler,
)


WEB_DIR = PROJECT_ROOT / "web"
INDEX_FILE = WEB_DIR / "index.html"
CUSTOMER_INDEX_FILE = WEB_DIR / "customer.html"
ADMIN_INDEX_FILE = WEB_DIR / "admin.html"
FAVICON_FILE = WEB_DIR / "favicon.svg"
HTML_RESPONSE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
}
RELOAD_DIRS = [
    PROJECT_ROOT / "app",
    PROJECT_ROOT / "web",
    PROJECT_ROOT / "prompts",
]

settings = get_settings()
configure_logging()
init_db()
if settings.knowledge_auto_import:
    try:
        import_knowledge_sources()
    except Exception as exc:
        logging.getLogger(__name__).warning("Knowledge auto import skipped: %s", exc)
if settings.demo_seed_data:
    seed_demo_environment()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await realtime_manager.start()
    start_sop_followup_scheduler()
    try:
        yield
    finally:
        await stop_sop_followup_scheduler()
        await realtime_manager.stop()


app = FastAPI(
    title=settings.app_name,
    version="0.17.0-demo",
    description="Sales Agent Windows showcase demo.",
    lifespan=lifespan,
)


@app.middleware("http")
async def add_json_utf8_charset(request, call_next):
    """显式声明 JSON 使用 UTF-8，避免 Windows PowerShell 按本地编码误解码中文。"""
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json") and "charset=" not in content_type:
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response


app.include_router(admin_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(websocket_router)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
@app.get("/")
async def index() -> RedirectResponse:
    return RedirectResponse(url="/sales")


@app.get("/sales")
async def sales_index() -> FileResponse:
    return FileResponse(INDEX_FILE, headers=HTML_RESPONSE_HEADERS)


@app.get("/customer")
async def customer_index() -> FileResponse:
    return FileResponse(CUSTOMER_INDEX_FILE, headers=HTML_RESPONSE_HEADERS)


@app.get("/admin")
async def admin_index() -> FileResponse:
    return FileResponse(ADMIN_INDEX_FILE, headers=HTML_RESPONSE_HEADERS)


@app.get("/favicon.ico")
async def favicon() -> FileResponse:
    return FileResponse(FAVICON_FILE, media_type="image/svg+xml")


@app.get("/health")
async def health_check() -> dict[str, str]:
    real_model_available = bool(build_llm_fallback_configs(settings))
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "runtime": "windows-python",
        "database": "postgresql",
        "llm": settings.llm_provider if real_model_available and not settings.demo_mode else "demo-fallback",
    }


def print_startup_links() -> None:
    display_host = (
        "127.0.0.1"
        if settings.app_host in {"0.0.0.0", "::", ""}
        else settings.app_host
    )
    current_base = f"http://{display_host}:{settings.app_port}"
    lines = [
        "",
        "Sales Agent 访问入口：",
        f"  销售端：{current_base}/sales",
        f"  客户模拟端：{current_base}/customer",
        f"  管理员端：{current_base}/admin",
        f"  实时通道：ws://{display_host}:{settings.app_port}/ws?viewer=sales|customer",
    ]
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    print_startup_links()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_reload,
        reload_dirs=(
            [str(path) for path in RELOAD_DIRS if path.exists()]
            if not settings.demo_mode
            else None
        ),
    )
