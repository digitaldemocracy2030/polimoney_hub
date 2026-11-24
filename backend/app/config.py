from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """アプリケーション設定

    アプリケーション全体の設定を管理するクラス。
    """

    # Application settings
    env: str = Field("development", env="ENV")
    debug: bool = Field(True, env="DEBUG")

    # Server settings
    host: str = Field("0.0.0.0", env="HOST")
    port: int = Field(3722, env="PORT")

    # CORS settings
    cors_origins: List[str] = Field(
        ["http://localhost:3000", "http://localhost:8080"], env="CORS_ORIGINS"
    )

    # Supabase settings
    supabase_url: Optional[str] = Field(None, env="SUPABASE_URL")
    supabase_secret_key: Optional[str] = Field(None, env="SUPABASE_SECRET_KEY")
    supabase_publishable_key: Optional[str] = Field(
        None, env="SUPABASE_PUBLISHABLE_KEY"
    )

    # Ledger 専用の同期 API キー（app/core/api_key.py）
    ledger_sync_api_key_prod: Optional[str] = Field(
        None, env="LEDGER_SYNC_API_KEY_PROD"
    )
    ledger_sync_api_key_dev: Optional[str] = Field(
        None, env="LEDGER_SYNC_API_KEY_DEV"
    )

    # 本人確認の確認コードのメール送信（Resend。app/services/mailer.py）
    # MAIL_FROM のドメインは Resend で認証しておくこと。例: "Polimoney <noreply@example.org>"
    resend_api_key: Optional[str] = Field(None, env="RESEND_API_KEY")
    mail_from: Optional[str] = Field(None, env="MAIL_FROM")

    class Config:
        """Pydantic設定

        Pydanticの設定クラス。
        """

        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
