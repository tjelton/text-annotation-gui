"""
data.py — Data structures for tokenisation, annotations, and file I/O.

Tokenisation matches slate exactly:
    for line in raw_text.split("\\n"):
        tokens = line.strip().split()

Annotation file format (slate-compatible):
    (line, token) - label:NAME
    ((line, start_token), (line, end_token)) - label:NAME1 label:NAME2
"""

import os
import re
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _natural_sort_key(s: str) -> list:
    """Natural sort so '10.txt' comes after '9.txt'."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]


def get_txt_files(folder: str) -> List[str]:
    """Return naturally-sorted list of .txt paths in *folder*."""
    entries = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith('.txt') and os.path.isfile(os.path.join(folder, f))
    ]
    return sorted(entries, key=lambda p: _natural_sort_key(os.path.basename(p)))


# ---------------------------------------------------------------------------
# TokenMap — maps between tkinter char positions and (slate_line, token) tuples
# ---------------------------------------------------------------------------

class TokenMap:
    """
    Pre-computes token positions for all lines in a document so we can quickly
    convert between tkinter 'line.char' indices and slate (line, token) tuples.

    Tkinter lines are 1-indexed; slate lines are 0-indexed.
    """

    def __init__(self, raw_text: str) -> None:
        self.raw_lines: List[str] = raw_text.split('\n')

        # tokens[i]           → list of token strings on slate line i
        # token_ranges[i][j]  → (start_char, end_char_inclusive) of token j in raw_lines[i]
        self.tokens: List[List[str]] = []
        self.token_ranges: List[List[Tuple[int, int]]] = []

        for line in self.raw_lines:
            toks: List[str] = []
            rngs: List[Tuple[int, int]] = []
            i, n = 0, len(line)
            while i < n:
                while i < n and line[i].isspace():
                    i += 1
                if i >= n:
                    break
                j = i
                while j < n and not line[j].isspace():
                    j += 1
                toks.append(line[i:j])
                rngs.append((i, j - 1))   # end is inclusive
                i = j
            self.tokens.append(toks)
            self.token_ranges.append(rngs)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def num_lines(self) -> int:
        return len(self.raw_lines)

    def num_tokens(self, slate_line: int) -> int:
        if 0 <= slate_line < len(self.tokens):
            return len(self.tokens[slate_line])
        return 0

    def char_to_token(self, slate_line: int, char_offset: int) -> Optional[int]:
        """
        Return the token index whose character range contains *char_offset*
        on *slate_line*, or the nearest token if the offset is in whitespace.
        Returns None if the line has no tokens.
        """
        if slate_line < 0 or slate_line >= len(self.token_ranges):
            return None
        ranges = self.token_ranges[slate_line]
        if not ranges:
            return None

        for i, (start, end) in enumerate(ranges):
            if start <= char_offset <= end:
                return i                          # exact hit
            if char_offset < start:
                # We're in whitespace before token i
                if i == 0:
                    return 0
                # Choose whichever token boundary is closer
                prev_end = ranges[i - 1][1]
                if (char_offset - prev_end) < (start - char_offset):
                    return i - 1
                return i

        # Past the last token
        return len(ranges) - 1

    def token_char_range(self, slate_line: int, token: int) -> Optional[Tuple[int, int]]:
        """Return (start_char, end_char_inclusive) of a token, or None."""
        if slate_line < 0 or slate_line >= len(self.token_ranges):
            return None
        if token < 0 or token >= len(self.token_ranges[slate_line]):
            return None
        return self.token_ranges[slate_line][token]

    # ------------------------------------------------------------------
    # Coordinate conversion helpers
    # ------------------------------------------------------------------

    def tk_to_slate(self, tk_index: str) -> Tuple[int, Optional[int]]:
        """
        Convert a tkinter 'line.char' index to (slate_line, token).
        Returns (slate_line, None) if the line carries no tokens.
        """
        tk_line_s, tk_char_s = tk_index.split('.')
        slate_line = int(tk_line_s) - 1          # 1-indexed → 0-indexed
        tk_char = int(tk_char_s)
        token = self.char_to_token(slate_line, tk_char)
        return (slate_line, token)

    def slate_to_tk_range(self, slate_line: int, token: int) -> Optional[Tuple[str, str]]:
        """
        Convert (slate_line, token) to a pair of tkinter indices
        ('line.start_char', 'line.end_char_exclusive').
        """
        cr = self.token_char_range(slate_line, token)
        if cr is None:
            return None
        start_char, end_char = cr
        tk_line = slate_line + 1                  # 0-indexed → 1-indexed
        return (f"{tk_line}.{start_char}", f"{tk_line}.{end_char + 1}")


# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------

class Annotation:
    """A single-line span annotated with one or more labels."""

    def __init__(
        self,
        line: int,
        start_token: int,
        end_token: int,
        labels: Optional[Set[str]] = None,
    ) -> None:
        self.line = line
        self.start_token = min(start_token, end_token)
        self.end_token = max(start_token, end_token)
        self.labels: Set[str] = set(labels) if labels else set()

    # ------------------------------------------------------------------

    def matches_span(self, line: int, start: int, end: int) -> bool:
        s, e = min(start, end), max(start, end)
        return self.line == line and self.start_token == s and self.end_token == e

    def overlaps_span(self, line: int, start: int, end: int) -> bool:
        if self.line != line:
            return False
        s, e = min(start, end), max(start, end)
        return not (self.end_token < s or self.start_token > e)

    def sort_key(self) -> Tuple[int, int, int]:
        return (self.line, self.start_token, self.end_token)

    def to_slate_str(self) -> Optional[str]:
        if not self.labels:
            return None
        labels_part = ' '.join(sorted(self.labels))
        if self.start_token == self.end_token:
            span_part = f"({self.line}, {self.start_token})"
        else:
            span_part = (
                f"(({self.line}, {self.start_token}), "
                f"({self.line}, {self.end_token}))"
            )
        return f"{span_part} - {labels_part}"

    def copy(self) -> 'Annotation':
        return Annotation(self.line, self.start_token, self.end_token,
                          self.labels.copy())

    def __repr__(self) -> str:
        return (f"Annotation(line={self.line}, "
                f"start={self.start_token}, end={self.end_token}, "
                f"labels={self.labels})")


# ---------------------------------------------------------------------------
# AnnotationSet
# ---------------------------------------------------------------------------

class AnnotationSet:
    """Collection of annotations for a single file."""

    def __init__(self) -> None:
        self.annotations: List[Annotation] = []

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_at_span(self, line: int, start: int, end: int) -> Optional[Annotation]:
        """Find the annotation at this exact span, or None."""
        s, e = min(start, end), max(start, end)
        for ann in self.annotations:
            if ann.matches_span(line, s, e):
                return ann
        return None

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def toggle_label(self, line: int, start: int, end: int, label: str) -> bool:
        """
        Toggle *label* on the span (line, start–end).
        Returns True if the label was added, False if it was removed.
        """
        existing = self.get_at_span(line, start, end)
        if existing is not None:
            if label in existing.labels:
                existing.labels.discard(label)
                if not existing.labels:
                    self.annotations.remove(existing)
                return False
            else:
                existing.labels.add(label)
                return True
        else:
            self.annotations.append(Annotation(line, start, end, {label}))
            return True

    def remove_overlapping(self, line: int, start: int, end: int) -> None:
        """Remove every annotation that overlaps (line, start–end)."""
        s, e = min(start, end), max(start, end)
        self.annotations = [
            a for a in self.annotations
            if not a.overlaps_span(line, s, e)
        ]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def get_all(self) -> List[Annotation]:
        return sorted(
            [a for a in self.annotations if a.labels],
            key=lambda a: a.sort_key(),
        )

    def save(self, filepath: str) -> None:
        """Write annotations to *filepath* in slate-compatible format."""
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            for ann in self.get_all():
                line_str = ann.to_slate_str()
                if line_str:
                    f.write(line_str + '\n')

    @classmethod
    def load(cls, filepath: str) -> 'AnnotationSet':
        """Read a slate-format annotation file, return an AnnotationSet."""
        ann_set = cls()
        if not os.path.isfile(filepath):
            return ann_set
        with open(filepath, 'r', encoding='utf-8') as f:
            for raw in f:
                raw = raw.strip()
                if not raw or ' - ' not in raw:
                    continue
                span_str, labels_str = raw.split(' - ', 1)
                labels = set(labels_str.split()) if labels_str.strip() else set()
                if not labels:
                    continue
                parsed = _parse_span(span_str.strip())
                if parsed is None:
                    continue
                line, start_tok, end_tok = parsed
                ann_set.annotations.append(
                    Annotation(line, start_tok, end_tok, labels)
                )
        return ann_set

    # ------------------------------------------------------------------
    # Undo support
    # ------------------------------------------------------------------

    def copy(self) -> 'AnnotationSet':
        new_set = AnnotationSet()
        new_set.annotations = [a.copy() for a in self.annotations]
        return new_set


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_span(span_str: str) -> Optional[Tuple[int, int, int]]:
    """
    Safely parse a span string into (line, start_token, end_token).
    Accepts:
        (line, token)
        ((line, start), (line, end))
    """
    # Single token: (line, token)
    m = re.match(r'^\(\s*(\d+)\s*,\s*(\d+)\s*\)$', span_str)
    if m:
        line, tok = int(m.group(1)), int(m.group(2))
        return (line, tok, tok)

    # Span: ((line, start), (line, end))
    m = re.match(
        r'^\(\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*,'
        r'\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*\)$',
        span_str,
    )
    if m:
        line1, start = int(m.group(1)), int(m.group(2))
        _line2, end = int(m.group(3)), int(m.group(4))
        return (line1, start, end)

    return None
