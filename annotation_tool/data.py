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
from typing import Callable, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _natural_sort_key(s: str) -> list:
    """Natural sort so '10.txt' comes after '9.txt'."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]


def get_txt_files(folder: str) -> List[str]:
    """Return naturally-sorted list of .txt paths in *folder*.

    Hidden files (e.g. macOS ``._01.txt`` metadata files) are skipped.
    """
    entries = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith('.txt') and not f.startswith('.')
        and os.path.isfile(os.path.join(folder, f))
    ]
    return sorted(entries, key=lambda p: _natural_sort_key(os.path.basename(p)))


def read_text(filepath: str) -> str:
    """Read a document as UTF-8.

    Raises OSError if the file cannot be read, or UnicodeDecodeError if it
    is not valid UTF-8 (e.g. saved as Windows-1252).
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


# ---------------------------------------------------------------------------
# TokenMap — maps between tkinter char positions and (slate_line, token) tuples
# ---------------------------------------------------------------------------

class TokenMap:
    """
    Pre-computes token positions for all lines in a document so we can quickly
    convert between tkinter 'line.char' indices and slate (line, token) tuples.

    Tkinter lines are 1-indexed; slate lines are 0-indexed.

    Character offsets are in the display widget's units.  Tk 8.x counts a
    character outside the Basic Multilingual Plane (e.g. an emoji) as more
    than one index position, so *astral_width* says how many positions one
    such character occupies (1 for plain Python offsets / Tk 9).  Token
    indices — the only thing written to annotation files — are unaffected.
    """

    def __init__(self, raw_text: str, astral_width: int = 1) -> None:
        self.raw_lines: List[str] = raw_text.split('\n')

        # tokens[i]           → list of token strings on slate line i
        # token_ranges[i][j]  → (start_char, end_char_inclusive) of token j on line i
        self.tokens: List[List[str]] = []
        self.token_ranges: List[List[Tuple[int, int]]] = []

        for line in self.raw_lines:
            # offsets[k] = widget offset of character k (plus one past the end)
            offsets: Optional[List[int]] = None
            if astral_width != 1 and any(ord(ch) > 0xFFFF for ch in line):
                offsets = [0]
                for ch in line:
                    offsets.append(offsets[-1] + (astral_width if ord(ch) > 0xFFFF else 1))

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
                if offsets is None:
                    rngs.append((i, j - 1))   # end is inclusive
                else:
                    rngs.append((offsets[i], offsets[j] - 1))
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
          'floor'    – always pick the previous token (do not overshoot right);
                       None if there is no token before *char_offset* on the line
          'ceiling'  – always pick the next token (do not overshoot left);
                       None if there is no token after *char_offset* on the line
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
                    # Nothing to the left on this line
                    return None if snap == 'floor' else 0
                if snap == 'floor':
                    return i - 1
                if snap == 'ceiling':
                    return i
                # nearest: choose whichever boundary is closer
                prev_end = ranges[i - 1][1]
                if (char_offset - prev_end) < (start - char_offset):
                    return i - 1
                return i

        # Past the last token: nothing to the right on this line
        return None if snap == 'ceiling' else len(ranges) - 1

    def is_after_last_token(self, slate_line: int, char_offset: int) -> bool:
        """True if no token on *slate_line* ends at or after *char_offset*."""
        ranges = self.token_ranges[slate_line] if 0 <= slate_line < len(self.token_ranges) else []
        return not ranges or char_offset > ranges[-1][1]

    def is_before_first_token(self, slate_line: int, char_offset: int) -> bool:
        """True if no token on *slate_line* starts at or before *char_offset*."""
        ranges = self.token_ranges[slate_line] if 0 <= slate_line < len(self.token_ranges) else []
        return not ranges or char_offset < ranges[0][0]

    def prev_token(self, slate_line: int, token: int) -> Optional[Tuple[int, int]]:
        """The (line, token) position just before this one, skipping blank lines."""
        if token > 0:
            return (slate_line, token - 1)
        for ln in range(slate_line - 1, -1, -1):
            n = self.num_tokens(ln)
            if n:
                return (ln, n - 1)
        return None

    def next_token(self, slate_line: int, token: int) -> Optional[Tuple[int, int]]:
        """The (line, token) position just after this one, skipping blank lines."""
        if token + 1 < self.num_tokens(slate_line):
            return (slate_line, token + 1)
        for ln in range(slate_line + 1, self.num_lines()):
            if self.num_tokens(ln):
                return (ln, 0)
        return None

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
        # Lines from the file that this tool can't represent (e.g. slate's
        # character-level spans, links, or items with no labels).  They are
        # written back unchanged on save so they are never lost.
        self.preserved_lines: List[str] = []

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

    def add_label(
        self, line: int, start: int, end: int, label: str,
        end_line: Optional[int] = None,
    ) -> None:
        """Ensure *label* is on the span (line, start) – (end_line, end)."""
        existing = self.get_at_span(line, start, end, end_line=end_line)
        if existing is not None:
            existing.labels.add(label)
        else:
            self.annotations.append(
                Annotation(line, start, end, {label}, end_line=end_line)
            )

    def remove_labels_in_range(
        self, labels: Set[str],
        start_line: int, start_tok: int, end_line: int, end_tok: int,
        token_map: 'TokenMap',
    ) -> None:
        """Remove *labels* from the tokens inside the span, and only there.

        An annotation that extends beyond the span keeps those labels on the
        part outside it: they are re-added as separate annotations covering
        the leftover piece before and/or after the span.  The annotation's
        other labels keep their original boundaries.
        """
        span_start = (start_line, start_tok)
        span_end = (end_line, end_tok)
        leftovers = []   # (piece_start, piece_end, labels)
        for ann in list(self.annotations):
            if not ann.overlaps_span_range(start_line, start_tok, end_line, end_tok):
                continue
            removed = ann.labels & labels
            if not removed:
                continue
            ann.labels -= removed
            if not ann.labels:
                self.annotations.remove(ann)
            ann_start = (ann.line, ann.start_token)
            ann_end = (ann.end_line, ann.end_token)
            if ann_start < span_start:
                before = token_map.prev_token(*span_start)
                if before is not None and ann_start <= before:
                    leftovers.append((ann_start, before, removed))
            if ann_end > span_end:
                after = token_map.next_token(*span_end)
                if after is not None and after <= ann_end:
                    leftovers.append((after, ann_end, removed))
        for (l1, t1), (l2, t2), piece_labels in leftovers:
            for label in piece_labels:
                self.add_label(l1, t1, t2, label,
                               end_line=l2 if l2 != l1 else None)

    def remove_labels_overlapping_range(
        self, labels: Set[str],
        start_line: int, start_tok: int, end_line: int, end_tok: int,
    ) -> int:
        """Remove *labels* from every annotation that overlaps the span.

        Like ``remove_overlapping_range`` but limited to *labels*: the
        annotations' other labels are kept.  Returns how many labels were
        removed.
        """
        removed = 0
        for ann in list(self.annotations):
            if not ann.overlaps_span_range(start_line, start_tok, end_line, end_tok):
                continue
            hit = ann.labels & labels
            if not hit:
                continue
            removed += len(hit)
            ann.labels -= hit
            if not ann.labels:
                self.annotations.remove(ann)
        return removed

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
        """Write annotations to *filepath* in slate-compatible format.

        The file is written to a temporary file first and then swapped into
        place, so a failed write (disk full, sync error) leaves the previous
        version intact instead of an empty or truncated file.
        """
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)
        lines = [a.to_slate_str() for a in self.get_all()]
        lines = [s for s in lines if s] + self.preserved_lines
        tmp_path = filepath + '.tmp'
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                for line in lines:
                    f.write(line + '\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, filepath)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @classmethod
    def load(cls, filepath: str) -> 'AnnotationSet':
        """Read a slate-format annotation file, return an AnnotationSet.

        Lines are split at the first '-' into span and labels, as slate does
        (span positions never contain '-', so hyphenated labels such as
        ``label:F-UP`` are safe).  Lines this tool can't represent are kept
        in ``preserved_lines``.  A UTF-8 byte-order mark is ignored.
        """
        ann_set = cls()
        if not os.path.isfile(filepath):
            return ann_set
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            for raw in f:
                line = raw.rstrip('\r\n')
                if not line.strip():
                    continue
                parsed, labels = None, set()
                if '-' in line:
                    span_str, labels_str = line.split('-', 1)
                    labels = set(labels_str.split())
                    parsed = _parse_span(span_str.strip())
                if parsed is None or not labels:
                    ann_set.preserved_lines.append(line)
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
        new_set.preserved_lines = list(self.preserved_lines)
        return new_set


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Adjudication support
# ---------------------------------------------------------------------------

# Annotator-name slot used for adjudication output files
# (``<txt>.adjudications.annotations``); never treated as an annotator.
ADJUDICATION_NAME = 'adjudications'
ANNOTATION_SUFFIX = '.annotations'


def find_annotators(
    folder: str, txt_basenames: List[str],
) -> List[Tuple[str, Dict[str, str]]]:
    """Find every annotator's annotation files in *folder*.

    Files are named ``<txt>.annotations`` (no annotator name) or
    ``<txt>.<name>.annotations``.  A folder may hold several annotators'
    files (e.g. a shared ``-o`` output folder); each distinct name is
    returned as a separate annotator.  Adjudication output
    (``<txt>.adjudications.annotations``) is ignored.

    Returns a list of (annotator_name, file_map) sorted by name, where
    *file_map* maps a txt basename to that annotator's annotation file and
    *annotator_name* is ``''`` for files without an embedded name.
    """
    # Try longer basenames first so "a.txt.b.txt" is not read as "a.txt" + name
    by_length = sorted(txt_basenames, key=len, reverse=True)
    found: Dict[str, Dict[str, str]] = {}
    for entry in sorted(os.listdir(folder)):
        if not entry.endswith(ANNOTATION_SUFFIX):
            continue
        path = os.path.join(folder, entry)
        if not os.path.isfile(path):
            continue
        stem = entry[:-len(ANNOTATION_SUFFIX)]
        for basename in by_length:
            if stem == basename:
                name = ''
            elif stem.startswith(basename + '.'):
                name = stem[len(basename) + 1:]
            else:
                continue
            if name != ADJUDICATION_NAME:
                found.setdefault(name, {})[basename] = path
            break
    return sorted(found.items())


def compute_adjudication(
    annotator_sets: List[Tuple[str, 'AnnotationSet']],
    token_map: 'TokenMap',
    partition_of: Optional[Callable[[str], Optional[str]]] = None,
) -> Tuple['AnnotationSet', Dict[Optional[str], set], dict, List[str]]:
    """Compare annotations from multiple annotators for a single document.

    An annotator with no annotations on the document (no file, or an empty
    one) most likely skipped it by mistake, so they are left out of the
    comparison and reported in *empty_annotators* instead of turning every
    other annotator's work into a disagreement.

    An annotation is *agreed* when every remaining annotator has an
    identical span (same line, start_token, end_line, end_token) with an
    identical label set.  Everything else is a disagreement.

    *partition_of*, if given, maps each label to the part of the scheme it
    belongs to (e.g. its group).  Each part of a span is then compared on
    its own, so annotators who agree on one part of a span still agree
    there when they differ on another.  Without it the whole label set is
    compared, as one part keyed None.

    Returns
    -------
    agreed_set : AnnotationSet
        Annotations identical across all compared annotators.
    disagreement_positions : dict
        ``{part: set of (slate_line, token)}``: token positions covered by
        at least one non-agreed annotation, for each part.
    token_annotator_info : dict
        ``{(line, token): {annotator_name: set_of_internal_labels}}``
    empty_annotators : list of str
        Names of annotators left out because they made no annotations.
    """
    empty_annotators = [
        name for name, ann_set in annotator_sets
        if not any(a.labels for a in ann_set.annotations)
    ]
    annotator_sets = [
        (name, ann_set) for name, ann_set in annotator_sets
        if name not in empty_annotators
    ]
    if not annotator_sets:
        return AnnotationSet(), {}, {}, empty_annotators

    def _part_keys(ann: Annotation) -> List[tuple]:
        """One comparison key per part of the scheme the labels fall in."""
        by_part: Dict[Optional[str], Set[str]] = {}
        for label in ann.labels:
            part = partition_of(label) if partition_of else None
            by_part.setdefault(part, set()).add(label)
        return [(part, ann.line, ann.start_token, ann.end_line, ann.end_token,
                 frozenset(labels)) for part, labels in by_part.items()]

    per_annotator_keys: List[set] = []
    for _name, ann_set in annotator_sets:
        keys = {k for a in ann_set.annotations for k in _part_keys(a)}
        per_annotator_keys.append(keys)

    agreed_keys = per_annotator_keys[0]
    for keys in per_annotator_keys[1:]:
        agreed_keys = agreed_keys & keys

    # Agreed parts of the same span go back into one annotation, as the
    # tool keeps all of a span's labels together.
    agreed_spans: Dict[tuple, Set[str]] = {}
    for _part, line, start_tok, end_line, end_tok, labels in agreed_keys:
        agreed_spans.setdefault((line, start_tok, end_line, end_tok), set()).update(labels)
    agreed_set = AnnotationSet()
    for (line, start_tok, end_line, end_tok), labels in agreed_spans.items():
        agreed_set.annotations.append(
            Annotation(line, start_tok, end_tok, labels, end_line=end_line)
        )

    def _covered_tokens(ann: Annotation) -> List[Tuple[int, int]]:
        positions: List[Tuple[int, int]] = []
        for sl in range(ann.line, ann.end_line + 1):
            n = token_map.num_tokens(sl)
            if n == 0:
                continue
            if sl == ann.line and sl == ann.end_line:
                ts, te = ann.start_token, ann.end_token
            elif sl == ann.line:
                ts, te = ann.start_token, n - 1
            elif sl == ann.end_line:
                ts, te = 0, ann.end_token
            else:
                ts, te = 0, n - 1
            for tok in range(ts, te + 1):
                positions.append((sl, tok))
        return positions

    disagreement_positions: Dict[Optional[str], set] = {}
    token_annotator_info: dict = {}

    for ann_name, ann_set in annotator_sets:
        for ann in ann_set.annotations:
            if not ann.labels:
                continue
            disputed = [k[0] for k in _part_keys(ann) if k not in agreed_keys]
            for pos in _covered_tokens(ann):
                for part in disputed:
                    disagreement_positions.setdefault(part, set()).add(pos)
                if pos not in token_annotator_info:
                    token_annotator_info[pos] = {}
                if ann_name not in token_annotator_info[pos]:
                    token_annotator_info[pos][ann_name] = set()
                token_annotator_info[pos][ann_name].update(ann.labels)

    return agreed_set, disagreement_positions, token_annotator_info, empty_annotators


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
