from pydantic import BaseModel, Field


class PublicationDate(BaseModel):
    year: str = ""
    month: str = ""
    day: str = ""
    medline: str = ""


class Article(BaseModel):
    pmid: str
    title: str = ""
    journal: str = ""
    publication_date: str = ""
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    keywords: list[str] = Field(default_factory=list)
    mesh_terms: list[str] = Field(default_factory=list)
    doi: str | None = None
    pmcid: str | None = None
    pubmed_url: str
    doi_url: str | None = None
    pmc_url: str | None = None


class SearchResponse(BaseModel):
    query: str
    count: int
    retstart: int
    retmax: int
    results: list[Article] = Field(default_factory=list)
