"""Hub 管理者の認証（/api/admin/*）

管理画面は Hub の Supabase Auth でログインし、アクセストークンを Authorization: Bearer で送る。
トークンを Supabase Auth で検証し、admin_users に登録されていて有効（is_active）な人だけを通す。
"""

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from supabase import Client

from app.database.supabase import get_admin_supabase_client_dep


@dataclass(frozen=True)
class AdminUser:
    id: str
    email: Optional[str]
    name: Optional[str]
    role: str


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin_user(
    authorization: Optional[str] = Header(default=None),
    supabase: Client = Depends(get_admin_supabase_client_dep),
) -> AdminUser:
    """Bearer トークンを検証し、Hub の管理者を返す FastAPI 依存関数"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("ログインが必要です")
    token = authorization[7:].strip()
    if not token:
        raise _unauthorized("ログインが必要です")

    try:
        user = supabase.auth.get_user(token).user
    except Exception:
        user = None
    if not user:
        raise _unauthorized("ログインの有効期限が切れています。再度ログインしてください")

    try:
        rows = (
            supabase.table("admin_users")
            .select("id, email, name, role, is_active")
            .eq("id", str(user.id))
            .limit(1)
            .execute()
            .data
        )
    except Exception as e:
        print(f"[AdminAuth] 管理者の取得に失敗しました: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="管理者の確認に失敗しました",
        )

    admin = rows[0] if rows else None
    if not admin or not admin.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理者として登録されていません",
        )

    return AdminUser(
        id=str(admin["id"]),
        email=admin.get("email"),
        name=admin.get("name"),
        role=admin.get("role") or "admin",
    )
