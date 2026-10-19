"""FastAPI Application Entry Point."""

from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from app.api.router import api_router
from app.core.config import settings


def create_application() -> FastAPI:
    """Application factory for FastAPI Document RAG service."""
    application = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Enterprise Document RAG (Retrieval-Augmented Generation) System API",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS configuration
    allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ]
    if settings.CORS_ORIGINS:
        for origin in settings.CORS_ORIGINS.split(","):
            origin_clean = origin.strip()
            if origin_clean and origin_clean not in allowed_origins:
                allowed_origins.append(origin_clean)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # Mount static assets for LexisPolicy AI Studio
    web_dir = Path("ui/web")
    if web_dir.exists():
        application.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

    # Mount exact ZIP-structure directories directly at their folder names
    exact_pages = [
        "page_1_policy_intelligence_dashboard",
        "page_2_ask_policy_workspace",
        "page_3_policy_change_intelligence",
        "page_4_document_library",
        "page_5_evaluations_benchmarks",
        "page_6_system_health",
        "page_7_about_architecture",
        "policy_intelligence_studio",
    ]
    for p_name in exact_pages:
        p_path = Path("ui") / p_name
        if p_path.exists():
            application.mount(f"/{p_name}", StaticFiles(directory=str(p_path), html=True), name=p_name)

    # Mount the ui directory under /pages for convenient tree navigation
    ui_dir = Path("ui")
    if ui_dir.exists():
        application.mount("/pages", StaticFiles(directory=str(ui_dir), html=True), name="pages")

    # Root endpoint: serves LexisPolicy AI Studio for browsers, JSON for API clients
    @application.get("/", tags=["Root"])
    async def root(request: Request):
        accept = request.headers.get("accept", "")
        if "application/json" in accept and "text/html" not in accept:
            return JSONResponse({
                "app": settings.APP_NAME,
                "version": "0.1.0",
                "status": "online",
                "docs": "/docs",
                "health": "/health",
                "streamlit_ui": "http://127.0.0.1:8501",
                "web_ui": "http://127.0.0.1:8000/",
            })
        index_file = web_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse({"app": settings.APP_NAME, "status": "online"})

    # Dedicated routes for all 7 UI studio layouts
    @application.get("/ui", tags=["UI"])
    @application.get("/dashboard", tags=["UI"])
    @application.get("/ask-policy", tags=["UI"])
    @application.get("/policy-change", tags=["UI"])
    @application.get("/document-library", tags=["UI"])
    @application.get("/evaluations", tags=["UI"])
    @application.get("/system-health", tags=["UI"])
    @application.get("/about-architecture", tags=["UI"])
    async def serve_studio_ui():
        index_file = web_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse({"error": "UI files not found"}, status_code=404)

    @application.get("/download-ui-zip", tags=["UI"])
    async def download_ui_zip():
        zip_path = Path("lexis_policy_ai_ui.zip")
        if zip_path.exists():
            return FileResponse(
                zip_path,
                filename="lexis_policy_ai_ui.zip",
                media_type="application/zip",
            )
        return JSONResponse({"error": "Zip file not found"}, status_code=404)

    # Mount API routers
    application.include_router(api_router)

    return application


app = create_application()

if __name__ == "__main__":
    import uvicorn

    # Default to localhost for secure development
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
