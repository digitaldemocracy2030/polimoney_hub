import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.admin_auth import require_admin_user
from app.core.api_key import require_ledger_api_key
from app.routers import (
    admin_ledger_requests,
    admin_verifications,
    election_funds,
    elections,
    health,
    ledger_requests,
    links,
    master,
    organizations,
    polimoney,
    political_funds,
    politicians,
    sync,
    verifications,
)
from app.utils.polimoney_response import MultipleCandidatesException

# Configure logging
logging.basicConfig(
    level=logging.INFO if settings.env == "development" else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPIアプリケーションのライフサイクルを管理するコンテキストマネージャー

    アプリケーション起動時にデータベースの初期化を行い、
    シャットダウン時にクリーンアップ処理を実行する。

    Args:
        app (FastAPI): FastAPIアプリケーションインスタンス

    Yields:
        None: アプリケーションの実行期間を示す

    Raises:
        Exception: データベース初期化に失敗した場合
    """
    logger.info("Starting Polimoney API server...")

    yield

    logger.info("Shutting down Polimoney API server...")


# Create FastAPI application
app = FastAPI(
    title="Polimoney API",
    description="政治資金収支報告書・選挙運動費用収支報告書管理システム",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """HTTPリクエストに一意のリクエストIDを付与するミドルウェア

    各リクエストに対してUUIDを生成し、レスポンスヘッダーに
    X-Request-IDとして追加する。これによりログの追跡と
    デバッグが容易になる。

    Args:
        request (Request): FastAPIのリクエストオブジェクト
        call_next (Callable): 次のミドルウェアまたはエンドポイントを呼び出す関数

    Returns:
        Response: リクエストIDが追加されたレスポンスオブジェクト
    """
    import uuid

    request_id = str(uuid.uuid4())

    response = await call_next(request)
    print(f"request_id: {request_id}", flush=True)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(MultipleCandidatesException)
async def multiple_candidates_exception_handler(
    request: Request,
    exc: MultipleCandidatesException,
):
    """複数候補者エラーを400レスポンスとして返却する

    Args:
        request: リクエスト
        exc: 複数候補者例外

    Returns:
        JSONResponse: 候補者一覧を含むエラーレスポンス
    """
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=exc.error.model_dump(mode="json"),
    )


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """アプリケーション全体の未処理例外をキャッチするグローバル例外ハンドラー

    予期せぬエラーが発生した場合に、適切なエラーレスポンスを返却し、
    ログにエラー情報を記録する。デバッグモード時は詳細なエラー情報を、
    本番環境時は一般的なエラーメッセージを返す。

    Args:
        request (Request): エラーが発生したリクエスト
        exc (Exception): 発生した例外オブジェクト

    Returns:
        JSONResponse: エラーレスポンスを含むJSONレスポンス
    """
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "Internal server error",
            "detail": str(exc) if settings.debug else "An unexpected error occurred",
        },
    )


# Include routers
app.include_router(health.router, tags=["health"])

# app.include_router(auth.router, prefix="/api/v1", tags=["authentication"])

# app.include_router(
#     users.router,
#     prefix="/api/v1/admin",
#     tags=["users"],
#     dependencies=[Depends(get_current_admin_user)],
# )

# /api/v1/* はすべて Ledger 専用 API キーが必要（app/core/api_key.py）。
# 一般公開用の API キーの仕組みができるまでは公開しない。/health だけは認証不要
LEDGER_API_DEPENDENCIES = [Depends(require_ledger_api_key)]

# 政治資金収支報告書のデータ取得
app.include_router(
    political_funds.router,
    prefix="/api/v1",
    tags=["political-funds"],
    dependencies=LEDGER_API_DEPENDENCIES,
)

# 選挙運動費用収支報告書のデータ取得
app.include_router(
    election_funds.router,
    prefix="/api/v1",
    tags=["election-funds"],
    dependencies=LEDGER_API_DEPENDENCIES,
)

# Polimoney向け公開データAPI
app.include_router(
    polimoney.router,
    prefix="/api/v1",
    tags=["polimoney"],
    dependencies=LEDGER_API_DEPENDENCIES,
)

# マスタデータAPI（勘定科目など）— 読み取り専用
app.include_router(
    master.router,
    prefix="/api/v1",
    tags=["master"],
    dependencies=LEDGER_API_DEPENDENCIES,
)

# 政治家・政治団体・選挙（Ledger 向け）
app.include_router(
    politicians.router,
    prefix="/api/v1",
    tags=["politicians"],
    dependencies=LEDGER_API_DEPENDENCIES,
)
app.include_router(
    organizations.router,
    prefix="/api/v1",
    tags=["organizations"],
    dependencies=LEDGER_API_DEPENDENCIES,
)
app.include_router(
    elections.router,
    prefix="/api/v1",
    tags=["elections"],
    dependencies=LEDGER_API_DEPENDENCIES,
)

# 政治家 ↔ 選挙 / 政治団体の紐付け（Ledger 向け）
app.include_router(
    links.router,
    prefix="/api/v1",
    tags=["links"],
    dependencies=LEDGER_API_DEPENDENCIES,
)

# 同期API（Ledger → Hub）
app.include_router(
    sync.router,
    prefix="/api/v1",
    tags=["sync"],
    dependencies=LEDGER_API_DEPENDENCIES,
)

# 本人確認（政治家・政治団体の管理者）の申請と確認（Ledger 向け）
app.include_router(
    verifications.router,
    prefix="/api/v1",
    tags=["verifications"],
    dependencies=LEDGER_API_DEPENDENCIES,
)

# 登録申請（選挙・政治団体）と年度のロック解除申請（Ledger 向け）
app.include_router(
    ledger_requests.router,
    prefix="/api/v1",
    tags=["requests"],
    dependencies=LEDGER_API_DEPENDENCIES,
)

# 管理者 API（Hub の Supabase Auth でログインし、admin_users に登録された人だけ）
app.include_router(
    admin_verifications.router,
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_user)],
)
app.include_router(
    admin_ledger_requests.router,
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_user)],
)


@app.get("/")
async def root():
    """APIのルートエンドポイント

    アプリケーションの基本情報を返却し、利用可能なエンドポイントへの
    リンクを提供する。APIの状態確認やドキュメントへのナビゲーションに使用する。

    Returns:
        dict: APIの基本情報と利用可能なエンドポイントのリンク
            - message (str): ウェルカムメッセージ
            - version (str): APIバージョン
            - docs (str): APIドキュメントのURL
            - health (str): ヘルスチェックエンドポイントのURL
    """
    return {
        "message": "Welcome to Polimoney API",
        "health": "/health",
    }
