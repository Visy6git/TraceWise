from pydantic import BaseModel, Field


class DocumentLocator(BaseModel):
    document_id: str
    block_id: str | None = None
    page: int | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None
    text_span_start: int | None = None
    text_span_end: int | None = None
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)


class SectionNode(BaseModel):
    section_id: str
    number: str
    title: str
    level: int = Field(ge=0)
    parent_id: str | None = None
    children: list[str] = Field(default_factory=list)
    locators: list[DocumentLocator] = Field(default_factory=list)
    is_leaf: bool = False
    extraction_status: str = "extracted"
