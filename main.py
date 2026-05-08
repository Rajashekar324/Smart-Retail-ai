from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import Base, engine
from app.routes.main import mount_routes
from app.database import SessionLocal
from app.services.seed import seed_data
# Import user management models to ensure tables are created
from app.services.user_management_service import Role, UserRole


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Fashion Store",
        description="AI powered fashion e-commerce platform",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handlers to ensure JSON responses
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail}
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        import traceback
        print(f"Global error: {str(exc)}")
        print(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "detail": "Internal server error"}
        )

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_data(db)

    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.mount("/app/uploads", StaticFiles(directory="app/uploads"), name="uploads")

    mount_routes(app)

    return app


app = create_app()