from typing import Any

from fastmcp import FastMCP

from app.pubmed_client import PubMedEUtilsClient


def register_tools(mcp: FastMCP, pubmed_client: PubMedEUtilsClient) -> None:
    @mcp.tool
    async def search_pubmed(
        query: str,
        max_results: int = 10,
        retstart: int = 0,
        sort: str = "relevance",
    ) -> dict[str, Any]:
        """Search PubMed with an E-utilities query and return article metadata."""
        result = await pubmed_client.search(
            query=query,
            max_results=max_results,
            retstart=retstart,
            sort=sort,
        )
        return result.model_dump()

    @mcp.tool
    async def get_pubmed_article(pmid: str) -> dict[str, Any]:
        """Get detailed metadata and abstract for a single PMID."""
        article = await pubmed_client.get_article(pmid)
        return article.model_dump()

    @mcp.tool
    async def get_pubmed_abstract(pmid: str) -> str:
        """Get only the abstract text for a PMID."""
        article = await pubmed_client.get_article(pmid)
        abstract = article.abstract.strip()
        if not abstract:
            return f"No abstract available for PMID {pmid}."
        return abstract
