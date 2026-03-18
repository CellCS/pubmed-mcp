from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastmcp import FastMCP

from app.config import BearerTokenMiddleware, settings
from app.pubmed_client import PubMedEUtilsClient
from app.tools import register_tools


pubmed_client = PubMedEUtilsClient(
    email=settings.pubmed_email,
    api_key=settings.pubmed_api_key,
    max_requests_per_second=settings.pubmed_eutils_limit,
)

mcp = FastMCP("pubmed-mcp")
register_tools(mcp, pubmed_client)


mcp_app = mcp.http_app(path="/")


@asynccontextmanager
async def app_lifespan(app_instance: FastAPI):
    async with mcp_app.lifespan(app_instance):
        yield
    await pubmed_client.close()


app = FastAPI(title="pubmed-mcp", lifespan=app_lifespan)
app.add_middleware(
    BearerTokenMiddleware,
    path_prefix=settings.normalized_mcp_http_path,
    valid_tokens=settings.bearer_tokens,
)
app.mount(settings.normalized_mcp_http_path, mcp_app)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
