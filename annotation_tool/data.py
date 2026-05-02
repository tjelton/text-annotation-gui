"""
data.py — Data structures for tokenisation, annotations, and file I/O.

Tokenisation matches slate exactly:
    for line in raw_text.split("\\n"):
        tokens = line.strip().split()

Annotation file format (slate-compatible):
    (line, token) - label:NAME
    ((line, start_token), (line, end_token)) - label:NAME1 label:NAME2
    ((start_line, start_token), (end_line, end_token)) - label:NAME  (multi-line)
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

    def char_to_token(self, slate_line: int, char_offset: int,
                      snap: str = 'nearest') -> Optional[int]:
        """
        Return the token index whose character range contains *char_offset*
        on *slate_line*.  Returns None if the line has no tokens.

        *snap* controls behaviour when *char_offset* falls in whitespace:
          'nearest'  – pick whichever adjacent token boundary is closer (default)
          'floor'    – always pick the previous token (do not overshoot right)
          'ceiling'  – always pick the next token (do not overshoot left)
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
                    return 0                      # nothing to the left
                if snap == 'floor':
                    return i - 1
                if snap == 'ceiling':
                    return i
                # nearest: choose whichever boundary is closer
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
    """A span (possibly multi-line) annotated with one or more labels."""

    def __init__(
        self,
        line: int,
        start_token: int,
        end_token: int,
        labels: Optional[Set[str]] = None,
        end_line: Optional[int] = None,
    ) -> None:
        self.line = line
        self.end_line = end_line if end_line is not None else line
        if self.line == self.end_line:
            self.start_token = min(start_token, end_token)
            self.end_token = max(start_token, end_token)
        else:
            self.start_token = start_token
            self.end_token = end_token
        self.labels: Set[str] = set(labels) if labels else set()

    # ------------------------------------------------------------------

    def matches_span(
        self, line: int, start: int, end: int,
        end_line: Optional[int] = None,
    ) -> bool:
        el = end_line if end_line is not None else line
        if self.line == el:
            s, e = min(start, end), max(start, end)
        else:
            s, e = start, end
        return (self.line == line and self.end_line == el
                and self.start_token == s and self.end_token == e)

    def overlaps_span(self, line: int, start: int, end: int) -> bool:
        """Return True if this annotation overlaps the single-line query."""
        if line < self.line or line > self.end_line:
            return False
        s, e = min(start, end), max(start, end)
        if self.line == self.end_line:
            # Single-line annotation — simple token range check
            return not (self.end_token < s or self.start_token > e)
        # Multi-line annotation
        if line == self.line:
            return e >= self.start_token
        if line == self.end_line:
            return s <= self.end_token
        # Strictly between start and end lines — always overlaps
        return True

    def overlaps_span_range(
        self, start_line: int, start_tok: int, end_line: int, end_tok: int,
    ) -> bool:
        """Return True if this annotation overlaps the multi-line span."""
        if self.end_line < start_line or self.line > end_line:
            return False
        if self.end_line == start_line and self.end_token < start_tok:
            return False
        if self.line == end_line and self.start_token > end_tok:
            return False
        return True

    def sort_key(self) -> Tuple[int, int, int, int]:
        return (self.line, self.start_token, self.end_line, self.end_token)

    def to_slate_str(self) -> Optional[str]:
        if not self.labels:
            return None
        labels_part = ' '.join(sorted(self.labels))
        if self.line == self.end_line and self.start_token == self.end_token:
            span_part = f"({self.line}, {self.start_token})"
        else:
            span_part = (
                f"(({self.line}, {self.start_token}), "
                f"({self.end_line}, {self.end_token}))"
            )
        return f"{span_part} - {labels_part}"

    def copy(self) -> 'Annotation':
        return Annotation(self.line, self.start_token, self.end_token,
                          self.labels.copy(), end_line=self.end_line)

    def __repr__(self) -> str:
        if self.line == self.end_line:
            return (f"Annotation(line={self.line}, "
                    f"start={self.start_token}, end={self.end_token}, "
                    f"labels={self.labels})")
        return (f"Annotation(line={self.line}, start={self.start_token}, "
                f"end_line={self.end_line}, end={self.end_token}, "
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

    def get_at_span(
        self, line: int, start: int, end: int,
        end_line: Optional[int] = None,
    ) -> Optional[Annotation]:
        """Find the annotation at this exact span, or None."""
        el = end_line if end_line is not None else line
        if line == el:
            s, e = min(start, end), max(start, end)
        else:
            s, e = start, end
        for ann in self.annotations:
            if ann.matches_span(line, s, e, end_line=el):
                return ann
        return None

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def toggle_label(
        self, line: int, start: int, end: int, label: str,
        end_line: Optional[int] = None,
    ) -> bool:
        """
        Toggle *label* on the span (line, start) – (end_line, end).
        Returns True if the label was added, False if it was removed.
        """
        existing = self.get_at_span(line, start, end, end_line=end_line)
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
            self.annotations.append(
                Annotation(line, start, end, {label}, end_line=end_line)
            )
            return True

    def remove_overlapping(self, line: int, start: int, end: int) -> None:
        """Remove every annotation that overlaps (line, start–end)."""
        s, e = min(start, end), max(start, end)
        self.annotations = [
            a for a in self.annotations
            if not a.overlaps_span(line, s, e)
        ]

    def remove_overlapping_range(
        self, start_line: int, start_tok: int, end_line: int, end_tok: int,
    ) -> None:
        """Remove every annotation that overlaps the multi-line span."""
        self.annotations = [
            a for a in self.annotations
            if not a.overlaps_span_range(start_line, start_tok, end_line, end_tok)
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
                start_line, start_tok, end_line, end_tok = parsed
                ann_set.annotations.append(
                    Annotation(start_line, start_tok, end_tok, labels,
                               end_line=end_line)
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

def _parse_span(span_str: str) -> Optional[Tuple[int, int, int, int]]:
    """
    Safely parse a span string into (start_line, start_token, end_line, end_token).
    Accepts:
        (line, token)
        ((start_line, start_token), (end_line, end_token))
    """
    # Single token: (line, token)
    m = re.match(r'^\(\s*(\d+)\s*,\s*(\d+)\s*\)$', span_str)
    if m:
        line, tok = int(m.group(1)), int(m.group(2))
        return (line, tok, line, tok)

    # Span: ((start_line, start), (end_line, end))
    m = re.match(
        r'^\(\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*,'
        r'\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*\)$',
        span_str,
    )
    if m:
        line1, start = int(m.group(1)), int(m.group(2))
        line2, end = int(m.group(3)), int(m.group(4))
        return (line1, start, line2, end)

    return None
