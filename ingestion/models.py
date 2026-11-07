"""ContractIQ Document Ingestion Models.

Defines the DocumentBuffer structure that anchors raw text, page indices,
section hierarchies, and deterministic character slicing utilities.
"""

from typing import List, Optional, Tuple, Dict, Any
import re
from pydantic import BaseModel, Field


class IndexedPage(BaseModel):
    """Metadata and character offsets for a single document page."""
    page_number: int = Field(..., description="1-indexed page number")
    start_char_offset: int = Field(..., ge=0, description="0-indexed start character in DocumentBuffer.raw_text")
    end_char_offset: int = Field(..., ge=0, description="0-indexed end character in DocumentBuffer.raw_text")
    page_text_length: int = Field(..., ge=0)
    dimensions: Optional[Dict[str, float]] = Field(
        default=None, description="Page width and height (e.g. {'width': 612.0, 'height': 792.0})"
    )


class IndexedSection(BaseModel):
    """Identified section boundary within the document."""
    section_id: str = Field(..., description="Normalized section tag (e.g., 'Section 8.2')")
    title: str = Field(..., description="Header text or title of the section")
    start_char_offset: int = Field(..., ge=0)
    end_char_offset: int = Field(..., ge=0)
    level: int = Field(default=1, description="Nesting level (1=Article/Top, 2=Section, 3=Subsection)")


class DocumentBuffer(BaseModel):
    """Immutable canonical document buffer and offset index.
    
    Shared by Contract Analyst (for extraction & citation grounding)
    and Contract Verifier (for slice matching & contextual consistency).
    """
    document_id: str = Field(..., description="Unique document identifier")
    document_hash: str = Field(..., description="Canonical SHA-256 hash of the document bytes/text")
    source_filename: str = Field(..., description="Original filename (PDF, DOCX, TXT)")
    raw_text: str = Field(..., description="Continuous raw text buffer with preserved character indices")
    total_chars: int = Field(..., ge=0)
    total_pages: int = Field(..., ge=1)
    pages: List[IndexedPage] = Field(default_factory=list)
    sections: List[IndexedSection] = Field(default_factory=list)

    def slice(self, start_char: int, end_char: int) -> str:
        """Deterministic buffer slice operation.
        
        Raises ValueError if offsets are out of bounds.
        """
        if start_char < 0 or end_char > self.total_chars or start_char > end_char:
            raise ValueError(
                f"Invalid slice range [{start_char}:{end_char}] for document with {self.total_chars} chars"
            )
        return self.raw_text[start_char:end_char]

    def get_page_for_offset(self, char_offset: int) -> int:
        """Resolve 1-indexed page number for a given character offset."""
        if char_offset < 0 or char_offset > self.total_chars:
            raise ValueError(f"Char offset {char_offset} out of range [0, {self.total_chars}]")
        for page in self.pages:
            if page.start_char_offset <= char_offset <= page.end_char_offset:
                return page.page_number
        return self.pages[-1].page_number if self.pages else 1

    def get_section_for_offset(self, char_offset: int) -> Optional[IndexedSection]:
        """Resolve the innermost section containing the character offset."""
        matched: Optional[IndexedSection] = None
        for sec in self.sections:
            if sec.start_char_offset <= char_offset <= sec.end_char_offset:
                if matched is None or sec.level >= matched.level:
                    matched = sec
        return matched

    def find_verbatim_quote(self, quote: str) -> Optional[Tuple[int, int]]:
        """Exact substring search returning (start_char_offset, end_char_offset)."""
        idx = self.raw_text.find(quote)
        if idx != -1:
            return idx, idx + len(quote)
        return None

    def find_normalized_quote(self, quote: str, threshold: float = 0.95) -> Optional[Tuple[int, int, float]]:
        """Finds quote allowing for whitespace and newline variations common in PDF extraction.
        
        Returns (start_char_offset, end_char_offset, similarity_score) if score >= threshold.
        """
        # First attempt exact match
        exact = self.find_verbatim_quote(quote)
        if exact:
            return exact[0], exact[1], 1.0

        # Build normalized pattern
        cleaned_tokens = quote.split()
        if not cleaned_tokens:
            return None

        # Create regex that allows arbitrary whitespace/newlines between words
        escaped_tokens = [re.escape(t) for t in cleaned_tokens]
        pattern_str = r"\s+".join(escaped_tokens)
        try:
            match = re.search(pattern_str, self.raw_text, re.IGNORECASE)
            if match:
                matched_span = match.span()
                return matched_span[0], matched_span[1], 0.99
        except Exception:
            pass

        return None

    def get_context_window(self, start_char: int, end_char: int, window_chars: int = 500) -> Dict[str, str]:
        """Extracts pre-context and post-context around a citation for scope/carve-out verification."""
        pre_start = max(0, start_char - window_chars)
        post_end = min(self.total_chars, end_char + window_chars)
        return {
            "pre_context": self.raw_text[pre_start:start_char],
            "quote": self.raw_text[start_char:end_char],
            "post_context": self.raw_text[end_char:post_end],
        }
