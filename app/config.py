from typing import Any

from fastapi.responses import JSONResponse
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.middleware.base import BaseHTTPMiddleware


class Settings(BaseSettings):
    pubmed_email: str = Field(alias="PUBMED_EMAIL")
    pubmed_api_key: str | None = Field(default=None, alias="PUBMED_API_KEY")
    pubmed_eutils_limit: int = Field(default=10, alias="PUBMED_EUTILS_LIMIT")
    mcp_http_path: str = Field(default="/pubmed-mcp", alias="MCP_HTTP_PATH")
    mcp_bearer_tokens: str = Field(default="", alias="MCP_BEARER_TOKENS")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def normalized_mcp_http_path(self) -> str:
        path = self.mcp_http_path.strip() or "/pubmed-mcp"
        if not path.startswith("/"):
            path = f"/{path}"
        return path.rstrip("/") or "/"

    @property
    def bearer_tokens(self) -> set[str]:
        raw_tokens = [token.strip() for token in self.mcp_bearer_tokens.split(",")]
        return {token for token in raw_tokens if token}


class BearerTokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, *, path_prefix: str, valid_tokens: set[str]) -> None:
        super().__init__(app)
        self.path_prefix = path_prefix
        self.valid_tokens = valid_tokens

    async def dispatch(self, request, call_next):
        if not self.valid_tokens or not request.url.path.startswith(self.path_prefix):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Missing Bearer token"})

        token = auth_header.removeprefix("Bearer ").strip()
        if token not in self.valid_tokens:
            return JSONResponse(status_code=403, content={"detail": "Invalid Bearer token"})

        return await call_next(request)


settings = Settings()
