import asyncio
import time
from typing import Any

import httpx
from defusedxml import ElementTree as ET

from app.models import Article, SearchResponse


class PubMedEUtilsClient:
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self, email: str, api_key: str | None, max_requests_per_second: int) -> None:
        self.email = email
        self.api_key = api_key
        self._min_interval = 1.0 / max(max_requests_per_second, 1)
        self._last_request = 0.0
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, endpoint: str, params: dict[str, Any]) -> httpx.Response:
        query = {**params, "email": self.email, "tool": "pubmed-mcp"}
        if self.api_key:
            query["api_key"] = self.api_key

        async with self._lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)

            response = await self._client.get(f"{self.base_url}/{endpoint}", params=query)
            self._last_request = time.monotonic()

        response.raise_for_status()
        return response

    async def _esearch(self, query: str, retmax: int, retstart: int = 0, sort: str = "relevance") -> dict[str, Any]:
        response = await self._request(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "retmode": "json",
                "term": query,
                "retmax": retmax,
                "retstart": retstart,
                "sort": sort,
            },
        )
        return response.json().get("esearchresult", {})

    async def _esummary(self, pmids: list[str]) -> dict[str, Any]:
        if not pmids:
            return {}
        response = await self._request(
            "esummary.fcgi",
            {
                "db": "pubmed",
                "retmode": "json",
                "version": "2.0",
                "id": ",".join(pmids),
            },
        )
        return response.json().get("result", {})

    async def _efetch(self, pmids: list[str]) -> str:
        if not pmids:
            return ""
        response = await self._request(
            "efetch.fcgi",
            {
                "db": "pubmed",
                "retmode": "xml",
                "rettype": "abstract",
                "id": ",".join(pmids),
            },
        )
        return response.text

    async def search(
        self,
        query: str,
        max_results: int = 10,
        retstart: int = 0,
        sort: str = "relevance",
    ) -> SearchResponse:
        retmax = max(1, min(max_results, 50))
        offset = max(0, retstart)
        search_result = await self._esearch(query=query, retmax=retmax, retstart=offset, sort=sort)

        pmids = search_result.get("idlist", [])
        if not pmids:
            return SearchResponse(
                query=query,
                count=int(search_result.get("count", 0)),
                retstart=offset,
                retmax=retmax,
                results=[],
            )

        summaries, xml_payload = await asyncio.gather(self._esummary(pmids), self._efetch(pmids))
        fetched = _parse_pubmed_articles(xml_payload)

        results: list[Article] = []
        for pmid in pmids:
            summary = summaries.get(pmid, {})
            details = fetched.get(pmid, {})
            results.append(_build_article(pmid=pmid, summary=summary, details=details))

        return SearchResponse(
            query=query,
            count=int(search_result.get("count", 0)),
            retstart=offset,
            retmax=retmax,
            results=results,
        )

    async def get_article(self, pmid: str) -> Article:
        clean_pmid = pmid.strip()
        if not clean_pmid:
            raise ValueError("PMID cannot be empty")

        summaries, xml_payload = await asyncio.gather(self._esummary([clean_pmid]), self._efetch([clean_pmid]))
        parsed = _parse_pubmed_articles(xml_payload).get(clean_pmid)
        summary = summaries.get(clean_pmid, {})

        if not parsed and not summary:
            raise ValueError(f"No PubMed record found for PMID {clean_pmid}")

        return _build_article(pmid=clean_pmid, summary=summary, details=parsed or {})


def _xml_text(element: Any | None, path: str) -> str:
    if element is None:
        return ""
    found = element.find(path)
    if found is None:
        return ""
    return "".join(found.itertext()).strip()


def _parse_pubmed_articles(xml_data: str) -> dict[str, dict[str, Any]]:
    if not xml_data.strip():
        return {}

    root = ET.fromstring(xml_data)
    parsed: dict[str, dict[str, Any]] = {}

    for node in root.findall(".//PubmedArticle"):
        pmid = _xml_text(node, "./MedlineCitation/PMID")
        if not pmid:
            continue

        abstract_nodes = node.findall(".//Article/Abstract/AbstractText")
        abstract_parts: list[str] = []
        for abstract_node in abstract_nodes:
            text = "".join(abstract_node.itertext()).strip()
            label = abstract_node.attrib.get("Label", "").strip()
            if text:
                abstract_parts.append(f"{label}: {text}" if label else text)

        authors: list[str] = []
        for author in node.findall(".//Article/AuthorList/Author"):
            collective = _xml_text(author, "./CollectiveName")
            if collective:
                authors.append(collective)
                continue

            last = _xml_text(author, "./LastName")
            fore = _xml_text(author, "./ForeName")
            name = f"{fore} {last}".strip()
            if name:
                authors.append(name)

        article_ids = node.findall(".//PubmedData/ArticleIdList/ArticleId")
        doi = ""
        pmcid = ""
        for article_id in article_ids:
            id_type = article_id.attrib.get("IdType", "")
            value = (article_id.text or "").strip()
            if id_type == "doi":
                doi = value
            if id_type == "pmc":
                pmcid = value

        parsed[pmid] = {
            "title": _xml_text(node, ".//Article/ArticleTitle"),
            "journal": _xml_text(node, ".//Article/Journal/Title"),
            "abstract": "\n\n".join(abstract_parts),
            "authors": authors,
            "doi": doi,
            "pmcid": pmcid,
            "keywords": [
                "".join(keyword.itertext()).strip()
                for keyword in node.findall(".//KeywordList/Keyword")
                if "".join(keyword.itertext()).strip()
            ],
            "mesh_terms": [
                "".join(mesh.itertext()).strip()
                for mesh in node.findall(".//MeshHeadingList/MeshHeading/DescriptorName")
                if "".join(mesh.itertext()).strip()
            ],
            "publication_date": {
                "year": _xml_text(node, ".//Article/Journal/JournalIssue/PubDate/Year"),
                "month": _xml_text(node, ".//Article/Journal/JournalIssue/PubDate/Month"),
                "day": _xml_text(node, ".//Article/Journal/JournalIssue/PubDate/Day"),
                "medline": _xml_text(node, ".//Article/Journal/JournalIssue/PubDate/MedlineDate"),
            },
        }

    return parsed


def _build_article(pmid: str, summary: dict[str, Any], details: dict[str, Any]) -> Article:
    doi = details.get("doi") or None
    pmcid = details.get("pmcid") or None

    return Article(
        pmid=pmid,
        title=summary.get("title") or details.get("title", ""),
        journal=summary.get("fulljournalname") or details.get("journal", ""),
        publication_date=summary.get("pubdate") or details.get("publication_date", {}).get("medline", ""),
        authors=[author.get("name") for author in summary.get("authors", []) if author.get("name")]
        or details.get("authors", []),
        abstract=details.get("abstract", ""),
        keywords=details.get("keywords", []),
        mesh_terms=details.get("mesh_terms", []),
        doi=doi,
        pmcid=pmcid,
        pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        doi_url=f"https://doi.org/{doi}" if doi else None,
        pmc_url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/" if pmcid else None,
    )
