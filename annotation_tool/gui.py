"""
gui.py — tkinter-based annotation GUI.

Layout (top to bottom):
    ┌─────────────────────────────────────────────┐
    │  [◀ Previous]  filename  (n/N)  [Save] [▶]  │  ← header
    ├─────────────────────────────────────────────┤
    │                                              │
    │   Text content (scrollable, read-only)       │  ← main area
    │                                              │
    ├─────────────────────────────────────────────┤
    │  Labels: [f] F-UP ██  [b] F-BK ██  …        │  ← legend
    ├─────────────────────────────────────────────┤
    │  Status: Ready                               │  ← status bar
    └─────────────────────────────────────────────┘
"""

import os
import sys
import tkinter as tk
from tkinter import messagebox
import tkinter.font as tkfont
from typing import List, Optional, Tuple

from .config import Config, LabelConfig
from .data import AnnotationSet, TokenMap, get_txt_files


# ---------------------------------------------------------------------------
# Colour utilities
# ---------------------------------------------------------------------------

def _contrast(hex_colour: str) -> str:
    """Return 'black' or 'white' for readable text on *hex_colour*."""
    c = hex_colour.lstrip('#')
    if len(c) == 3:
        c = ''.join(ch * 2 for ch in c)
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return 'black' if luminance > 0.5 else 'white'


# ---------------------------------------------------------------------------
# Main application class
# ---------------------------------------------------------------------------

class AnnotationApp:
    """The complete annotation GUI."""

    # Multi-label overlap colour (used when several labels share a token)
    MULTI_LABEL_COLOUR = '#7f8c8d'
    MULTI_LABEL_TAG    = 'multi_lbl'
    PIPE_TAG           = '_pipe_delim'
    SELECT_DEFAULT_BG  = '#aed6f1'
    SELECT_LABELLED_BG = '#a8e6cf'

    def __init__(
        self,
        root: tk.Tk,
        config: Config,
        files: List[str],
        output_dir: Optional[str],
        annotator: str,
    ) -> None:
        self.root = root
        self.config = config
        self.files = files
        self.output_dir = output_dir
        self.annotator = annotator

        self.current_idx: int = 0
        self.token_map: Optional[TokenMap] = None
        self.annotation_set = AnnotationSet()
        self.undo_stack: List[AnnotationSet] = []
        self.has_unsaved: bool = False

        # The snapped selection: (start_line, start_tok, end_line, end_tok) — all 0-indexed
        self.current_span: Optional[Tuple[int, int, int, int]] = None
        self._drag_anchor: Optional[str] = None

        # Font size for the text area (adjustable at runtime)
        self.font_size: int = 13

        # Cache for composite style tags (used when multiple style labels overlap)
        self._combo_tags: dict = {}

        self._build_ui()
        self._configure_tags()
        self._bind_keys()
        self._load_file(0)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.root.title("Annotation Tool")
        self.root.geometry("960x740")
        self.root.minsize(640, 480)
        self.root.configure(bg='#2c3e50')

        # ── Header ────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg='#2c3e50', padx=8, pady=6)
        hdr.pack(fill='x', side='top')

        self.btn_prev = tk.Button(
            hdr, text='◀  Previous', command=self._go_prev,
            bg='#34495e', fg='black', activebackground='#4a6278',
            activeforeground='black', relief='flat', padx=10, pady=5,
            font=('Helvetica', 11),
        )
        self.btn_prev.pack(side='left', padx=(0, 8))

        self.lbl_filename = tk.Label(
            hdr, text='', fg='white', bg='#2c3e50',
            font=('Helvetica', 13, 'bold'),
        )
        self.lbl_filename.pack(side='left', expand=True)

        self.lbl_progress = tk.Label(
            hdr, text='', fg='#bdc3c7', bg='#2c3e50',
            font=('Helvetica', 11),
        )
        self.lbl_progress.pack(side='left', padx=10)

        tk.Button(
            hdr, text='－', command=lambda: self._change_font_size(-1),
            bg='#34495e', fg='black', activebackground='#4a6278',
            activeforeground='black', relief='flat', padx=8, pady=5,
            font=('Helvetica', 11),
        ).pack(side='left', padx=(0, 2))

        tk.Button(
            hdr, text='＋', command=lambda: self._change_font_size(1),
            bg='#34495e', fg='black', activebackground='#4a6278',
            activeforeground='black', relief='flat', padx=8, pady=5,
            font=('Helvetica', 11),
        ).pack(side='left', padx=(0, 6))

        btn_save = tk.Button(
            hdr, text='Save', command=self._save_current,
            bg='#27ae60', fg='black', activebackground='#2ecc71',
            activeforeground='black', relief='flat', padx=10, pady=5,
            font=('Helvetica', 11),
        )
        btn_save.pack(side='left', padx=6)

        btn_help = tk.Button(
            hdr, text='Help', command=self._show_help,
            bg='#34495e', fg='black', activebackground='#4a6278',
            activeforeground='black', relief='flat', padx=10, pady=5,
            font=('Helvetica', 11),
        )
        btn_help.pack(side='left', padx=6)

        self.btn_next = tk.Button(
            hdr, text='Next  ▶', command=self._go_next,
            bg='#34495e', fg='black', activebackground='#4a6278',
            activeforeground='black', relief='flat', padx=10, pady=5,
            font=('Helvetica', 11),
        )
        self.btn_next.pack(side='left')

        # ── Status bar ────────────────────────────────────────────────
        status_frame = tk.Frame(self.root, bg='#bdc3c7')
        status_frame.pack(fill='x', side='bottom')

        self.status_var = tk.StringVar(value='Ready')
        tk.Label(
            status_frame, textvariable=self.status_var,
            anchor='w', bg='#bdc3c7', fg='#2c3e50',
            font=('Helvetica', 10), padx=10, pady=3,
        ).pack(side='left', fill='x', expand=True)

        self.cursor_tags_var = tk.StringVar(value='')
        self.cursor_tags_label = tk.Label(
            status_frame, textvariable=self.cursor_tags_var,
            anchor='e', bg='#bdc3c7', fg='#2c3e50',
            font=('Helvetica', 10, 'bold'), padx=10, pady=3,
            relief='flat',
        )
        self.cursor_tags_label.pack(side='right')

        # ── Legend panel ──────────────────────────────────────────────
        legend_frame = tk.Frame(self.root, bg='#ecf0f1', relief='groove', bd=1)
        legend_frame.pack(fill='x', side='bottom', padx=0, pady=0)

        tk.Label(
            legend_frame, text='Labels:', bg='#ecf0f1', fg='black',
            font=('Helvetica', 10, 'bold'), padx=8, pady=5,
        ).pack(side='left')

        for lc in self.config.labels.values():
            cell = tk.Frame(legend_frame, bg='#ecf0f1', padx=4, pady=4)
            cell.pack(side='left')
            tk.Label(
                cell, text=f'[{lc.key}]', bg='#ecf0f1',
                font=('Courier', 10, 'bold'), fg='#2c3e50',
            ).pack(side='left')
            if lc.style:
                swatch_font = tkfont.Font(
                    family='Helvetica', size=10,
                    weight='bold' if lc.style == 'bold' else 'normal',
                    slant='italic' if lc.style == 'italic' else 'roman',
                    underline=lc.style == 'underline',
                )
                tk.Label(
                    cell,
                    text=f' {lc.name} ',
                    bg='#ecf0f1',
                    fg='#2c3e50',
                    font=swatch_font,
                    relief='groove', padx=4, pady=2,
                ).pack(side='left', padx=(2, 4))
            else:
                tk.Label(
                    cell,
                    text=f' {lc.name} ',
                    bg=lc.colour,
                    fg='black',
                    font=('Helvetica', 10, 'bold'),
                    relief='flat', padx=4, pady=2,
                ).pack(side='left', padx=(2, 4))

        # Multi-label indicator in legend
        cell = tk.Frame(legend_frame, bg='#ecf0f1', padx=4, pady=4)
        cell.pack(side='left')
        tk.Label(
            cell, text='[overlap]', bg='#ecf0f1',
            font=('Courier', 10), fg='#7f8c8d',
        ).pack(side='left')
        tk.Label(
            cell,
            text=' multi-coloured ',
            bg=self.MULTI_LABEL_COLOUR,
            fg='white',
            font=('Helvetica', 10),
            relief='flat', padx=4, pady=2,
        ).pack(side='left', padx=(2, 4))

        # ── Text area ─────────────────────────────────────────────────
        text_outer = tk.Frame(self.root, bg='white')
        text_outer.pack(fill='both', expand=True, padx=0, pady=0)

        scrollbar = tk.Scrollbar(text_outer)
        scrollbar.pack(side='right', fill='y')

        self.text_widget = tk.Text(
            text_outer,
            wrap='word',
            font=('Helvetica', self.font_size),
            yscrollcommand=scrollbar.set,
            # Keep 'normal' so we can intercept key events reliably;
            # all text-modification keys are blocked in _on_key_press.
            state='normal',
            cursor='xterm',
            padx=16, pady=12,
            spacing1=4, spacing2=2, spacing3=4,
            selectbackground=self.SELECT_DEFAULT_BG,
            selectforeground='black',
            bg='#fdfefe',
            fg='#2c3e50',
        )
        self.text_widget.pack(fill='both', expand=True)
        scrollbar.config(command=self.text_widget.yview)

    # ------------------------------------------------------------------
    # Tag configuration
    # ------------------------------------------------------------------

    def _configure_tags(self) -> None:
        """Register tkinter Text tags for each label and for multi-label spans."""
        for lc in self.config.labels.values():
            if lc.style:
                opts: dict = {}
                if lc.style == 'bold':
                    opts['font'] = ('Helvetica', self.font_size, 'bold')
                elif lc.style == 'italic':
                    opts['font'] = ('Helvetica', self.font_size, 'italic')
                elif lc.style == 'underline':
                    opts['underline'] = True
                self.text_widget.tag_configure(lc.tag, **opts)
            else:
                self.text_widget.tag_configure(
                    lc.tag,
                    background=lc.colour,
                    foreground=_contrast(lc.colour),
                )
        self.text_widget.tag_configure(
            self.MULTI_LABEL_TAG,
            background=self.MULTI_LABEL_COLOUR,
            foreground='white',
            underline=True,
        )
        self.text_widget.tag_configure(
            self.PIPE_TAG,
            font=('Helvetica', self.font_size),
            foreground='#888888',
        )
        # Ensure the selection highlight (sel) always appears on top
        self.text_widget.tag_raise('sel')

    # ------------------------------------------------------------------
    # Key bindings
    # ------------------------------------------------------------------

    def _bind_keys(self) -> None:
        """Bind all keyboard shortcuts."""
        # Intercept ALL key presses on the text widget.
        # We return 'break' to block any text modifications.
        self.text_widget.bind('<Key>', self._on_key_press)

        # Mouse bindings
        self.text_widget.bind('<ButtonRelease-1>', self._on_mouse_release)
        self.text_widget.bind('<Button-1>', self._on_mouse_click)
        self.text_widget.bind('<Motion>', self._on_mouse_motion)
        self.text_widget.bind('<Leave>', lambda e: self._update_cursor_tags([]))

        # Window close
        self.root.protocol('WM_DELETE_WINDOW', self._quit)

    def _on_key_press(self, event: tk.Event) -> str:
        """
        Central keyboard handler.  All label keys, navigation keys, and
        Ctrl shortcuts are dispatched from here.  Returns 'break' to
        prevent the default Text-widget key handler from modifying text.
        """
        keysym = event.keysym         # e.g. 'f', 'bracketright', 'Escape'
        char   = event.char           # e.g. 'f', ']', ''
        ctrl   = bool(event.state & 0x4)   # Ctrl held
        # On Windows, bit 0x8 is Num Lock (not Command), so gate this to macOS
        # or every keypress would be treated as Cmd-held when Num Lock is on.
        cmd    = sys.platform == 'darwin' and bool(event.state & 0x8)

        # --- Ctrl / Cmd shortcuts ----------------------------------------
        if ctrl or cmd:
            k = keysym.lower()
            if k == 's':
                self._save_current()
            elif k == 'z':
                self._undo()
            elif k == 'q':
                self._quit()
            elif k in ('equal', 'plus'):
                self._change_font_size(1)
            elif k == 'minus':
                self._change_font_size(-1)
            elif k in ('c', 'a'):
                return  # Allow copy and select-all
            return 'break'

        # --- Escape ----------------------------------------------------------
        if keysym == 'Escape':
            self._clear_selection()
            return 'break'

        # --- Navigation keys -----------------------------------------------
        if keysym == 'bracketright' or char == ']':
            self._go_next()
            return 'break'
        if keysym == 'bracketleft' or char == '[':
            self._go_prev()
            return 'break'

        # --- Remove annotations ('u') ----------------------------------------
        if char == 'u' or keysym == 'u':
            self._remove_selected_annotations()
            return 'break'

        # --- Scrolling (allow default behaviour) -----------------------------
        if keysym in ('Up', 'Down', 'Prior', 'Next', 'Home', 'End'):
            return  # Let the Text widget scroll normally

        # --- Label keys (from config) ----------------------------------------
        if char and char in self.config.labels:
            self._apply_label(self.config.labels[char])
            return 'break'

        # --- Block everything else -------------------------------------------
        return 'break'

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _annotation_path(self, filepath: str) -> str:
        basename = os.path.basename(filepath)
        if self.annotator:
            ann_filename = f"{basename}.{self.annotator}.annotations"
        else:
            ann_filename = f"{basename}.annotations"
        if self.output_dir:
            return os.path.join(self.output_dir, ann_filename)
        return os.path.join(os.path.dirname(filepath), ann_filename)

    def _load_file(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.files):
            return

        self.current_idx = idx
        filepath = self.files[idx]

        # Read raw text
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except OSError as exc:
            self.status_var.set(f"Error reading {os.path.basename(filepath)}: {exc}")
            return

        # Build token map
        self.token_map = TokenMap(content)

        # Check the file has at least one token
        total_tokens = sum(
            self.token_map.num_tokens(l)
            for l in range(self.token_map.num_lines())
        )
        if total_tokens == 0:
            self.status_var.set(
                f"Warning: {os.path.basename(filepath)} appears to be empty."
            )

        # Load (or reset) annotations
        ann_path = self._annotation_path(filepath)
        self.annotation_set = AnnotationSet.load(ann_path)
        self.undo_stack.clear()
        self.has_unsaved = False
        self.current_span = None
        self._update_cursor_tags([])

        # Populate text widget
        self.text_widget.config(state='normal')
        self.text_widget.delete('1.0', 'end')
        self.text_widget.insert('1.0', content)
        # Keep state='normal' so key events fire; key handler blocks modifications.

        # Draw existing annotations
        self._redraw_annotations()

        # Update header / status
        self._update_header()
        self.status_var.set(f"Loaded: {os.path.basename(filepath)}")
        self.text_widget.focus_set()

    def _update_header(self) -> None:
        filepath = self.files[self.current_idx]
        basename = os.path.basename(filepath)
        title = f"{self.annotator}  —  {basename}" if self.annotator else basename
        self.lbl_filename.config(text=title)
        self.lbl_progress.config(
            text=f"({self.current_idx + 1} / {len(self.files)})"
        )
        self.btn_prev.config(
            state='normal' if self.current_idx > 0 else 'disabled'
        )
        self.btn_next.config(
            state='normal' if self.current_idx < len(self.files) - 1 else 'disabled'
        )

    # ------------------------------------------------------------------
    # Annotation rendering
    # ------------------------------------------------------------------

    def _redraw_annotations(self) -> None:
        """
        Clear all annotation tags then re-apply them from self.annotation_set.

        Strategy: for each (slate_line, token) position, collect all labels
        that cover it.  Apply the single-label colour if exactly one label,
        or the multi-label colour if more than one.  Contiguous tokens with
        the same tag are merged into a single range so whitespace between
        them is also highlighted.
        """
        if self.token_map is None:
            return

        # Remove previously inserted pipe delimiters (reverse order to preserve positions)
        pipe_ranges = self.text_widget.tag_ranges(self.PIPE_TAG)
        for i in range(len(pipe_ranges) - 2, -1, -2):
            self.text_widget.delete(pipe_ranges[i], pipe_ranges[i + 1])

        # Remove existing annotation tags
        for lc in self.config.labels.values():
            self.text_widget.tag_remove(lc.tag, '1.0', 'end')
        self.text_widget.tag_remove(self.MULTI_LABEL_TAG, '1.0', 'end')
        for combo_tag in self._combo_tags.values():
            self.text_widget.tag_remove(combo_tag, '1.0', 'end')

        # Build per-token label sets and annotation-identity sets:
        # (slate_line, token) → set of internal label names
        # (slate_line, token) → frozenset of annotation ids (to detect span boundaries)
        pos_labels: dict = {}
        pos_ann_ids: dict = {}
        for ann in self.annotation_set.annotations:
            if not ann.labels:
                continue
            ann_id = id(ann)
            for sl in range(ann.line, ann.end_line + 1):
                n = self.token_map.num_tokens(sl)
                if n == 0:
                    continue
                if sl == ann.line and sl == ann.end_line:
                    tok_start, tok_end = ann.start_token, ann.end_token
                elif sl == ann.line:
                    tok_start, tok_end = ann.start_token, n - 1
                elif sl == ann.end_line:
                    tok_start, tok_end = 0, ann.end_token
                else:
                    tok_start, tok_end = 0, n - 1
                for tok in range(tok_start, tok_end + 1):
                    key = (sl, tok)
                    if key not in pos_labels:
                        pos_labels[key] = set()
                        pos_ann_ids[key] = set()
                    pos_labels[key].update(ann.labels)
                    pos_ann_ids[key].add(ann_id)

        # Resolve each token position to a tag name
        line_tok_tags: dict = {}  # slate_line → {token: (tag_name, ann_key)}
        for (sl, tok), labels in pos_labels.items():
            if sl not in line_tok_tags:
                line_tok_tags[sl] = {}
            tag = self._resolve_tag(labels)
            if tag:
                ann_key = frozenset(pos_ann_ids[(sl, tok)])
                line_tok_tags[sl][tok] = (tag, ann_key)

        # Apply tags, merging contiguous runs of the same tag to fill gaps.
        # Break runs at annotation boundaries so adjacent same-label spans
        # remain visually distinct.
        for sl, tok_tags in line_tok_tags.items():
            sorted_toks = sorted(tok_tags.keys())
            if not sorted_toks:
                continue
            run_start = sorted_toks[0]
            run_tag, run_ann = tok_tags[run_start]
            prev = run_start
            for tok in sorted_toks[1:]:
                cur_tag, cur_ann = tok_tags[tok]
                if tok == prev + 1 and cur_tag == run_tag and cur_ann == run_ann:
                    prev = tok
                else:
                    self._apply_tag_run(sl, run_start, prev, run_tag)
                    run_start, run_tag, run_ann, prev = tok, cur_tag, cur_ann, tok
            self._apply_tag_run(sl, run_start, prev, run_tag)

        # Insert pipe delimiters at boundaries of styled (bold/italic/underline) spans
        self._insert_style_pipes()
        self._propagate_tags_to_pipes()

        # Keep selection on top
        self.text_widget.tag_raise('sel')

    def _apply_tag_run(self, sl: int, start_tok: int, end_tok: int, tag: str) -> None:
        """Tag from the start of start_tok to the end of end_tok on slate line sl."""
        start_cr = self.token_map.token_char_range(sl, start_tok)
        end_cr   = self.token_map.token_char_range(sl, end_tok)
        if start_cr and end_cr:
            tk_line = sl + 1
            self.text_widget.tag_add(
                tag,
                f"{tk_line}.{start_cr[0]}",
                f"{tk_line}.{end_cr[1] + 1}",
            )

    def _resolve_tag(self, labels: set) -> str:
        """Resolve a set of label internals to a single tkinter tag name.

        For a single label, returns its pre-configured tag.  For multiple
        labels, creates (and caches) a composite tag that combines all
        visual properties — overlapping text styles merge naturally while
        overlapping colours fall back to the multi-label grey.
        """
        if len(labels) == 1:
            internal = next(iter(labels))
            lc = self.config.internal_to_config.get(internal)
            return lc.tag if lc else self.MULTI_LABEL_TAG

        key = frozenset(labels)
        if key in self._combo_tags:
            return self._combo_tags[key]

        # Separate style-based and colour-based labels
        styles: set = set()
        colour_lcs: list = []
        for internal in labels:
            lc = self.config.internal_to_config.get(internal)
            if not lc:
                continue
            if lc.style:
                styles.add(lc.style)
            elif lc.colour:
                colour_lcs.append(lc)

        opts: dict = {}

        # Background colour
        if len(colour_lcs) == 1:
            opts['background'] = colour_lcs[0].colour
            opts['foreground'] = _contrast(colour_lcs[0].colour)
        elif len(colour_lcs) > 1:
            opts['background'] = self.MULTI_LABEL_COLOUR
            opts['foreground'] = 'white'

        # Font styles
        font_parts = []
        if 'bold' in styles:
            font_parts.append('bold')
        if 'italic' in styles:
            font_parts.append('italic')
        if font_parts:
            opts['font'] = ('Helvetica', self.font_size, ' '.join(font_parts))
        if 'underline' in styles:
            opts['underline'] = True

        if not opts:
            return self.MULTI_LABEL_TAG

        # Build a deterministic tag name
        tag_name = 'combo_' + '_'.join(
            s.replace(':', '_').replace('-', '_') for s in sorted(labels)
        )
        self.text_widget.tag_configure(tag_name, **opts)
        self._combo_tags[key] = tag_name
        return tag_name

    # ------------------------------------------------------------------
    # Pipe-delimiter offset correction
    # ------------------------------------------------------------------

    def _strip_pipe_offset(self, tk_line: int, tk_char: int) -> int:
        """
        Return *tk_char* adjusted for pipe-delimiter characters inserted on
        *tk_line* before that position.  The TokenMap knows only the original
        text, so any tkinter char offset must be reduced by the number of
        pipe chars that precede it on the same line.
        """
        offset = 0
        for i, (r_start, r_end) in enumerate(
            zip(*[iter(self.text_widget.tag_ranges(self.PIPE_TAG))] * 2)
        ):
            s_line, s_char = [int(x) for x in str(r_start).split('.')]
            e_line, e_char = [int(x) for x in str(r_end).split('.')]
            if s_line < tk_line:
                continue
            if s_line > tk_line:
                break
            if s_char >= tk_char:
                break
            offset += min(e_char, tk_char) - s_char
        return tk_char - offset

    def _add_pipe_offset(self, tk_line: int, orig_char: int) -> int:
        """
        Inverse of *_strip_pipe_offset*: given a character position in the
        *original* text, return the corresponding position in the widget text
        (which contains inserted pipe-delimiter characters).
        """
        offset = 0
        for r_start, r_end in zip(
            *[iter(self.text_widget.tag_ranges(self.PIPE_TAG))] * 2
        ):
            s_line, s_char = [int(x) for x in str(r_start).split('.')]
            e_line, e_char = [int(x) for x in str(r_end).split('.')]
            if s_line < tk_line:
                continue
            if s_line > tk_line:
                break
            pipe_len = e_char - s_char
            # This pipe range starts at s_char in widget text.  In original
            # text that corresponds to (s_char - offset).  If the original
            # position is at or past that point the pipe precedes it.
            if (s_char - offset) > orig_char:
                break
            offset += pipe_len
        return orig_char + offset

    # ------------------------------------------------------------------
    # Style-span pipe delimiters
    # ------------------------------------------------------------------

    def _insert_style_pipes(self) -> None:
        """Insert [ ] at the boundaries of styled (bold/italic/underline) spans."""
        if self.token_map is None:
            return

        styled_internals = {
            lc.internal for lc in self.config.labels.values() if lc.style
        }
        if not styled_internals:
            return

        # Collect open ([) and close (]) positions separately.
        # For multi-line annotations, [ goes on the start line, ] on the end line.
        open_positions: set = set()
        close_positions: set = set()
        for ann in self.annotation_set.annotations:
            if not ann.labels or not (ann.labels & styled_internals):
                continue
            start_cr = self.token_map.token_char_range(ann.line, ann.start_token)
            end_cr = self.token_map.token_char_range(ann.end_line, ann.end_token)
            if start_cr and end_cr:
                open_positions.add((ann.line + 1, start_cr[0]))
                close_positions.add((ann.end_line + 1, end_cr[1] + 1))

        if not open_positions and not close_positions:
            return

        # Merge all positions; where close and open coincide, emit '] [' as one insert
        all_pos = open_positions | close_positions
        for pos in sorted(all_pos, reverse=True):
            is_open = pos in open_positions
            is_close = pos in close_positions
            if is_open and is_close:
                text = '] ['
            elif is_close:
                text = '] '
            else:
                text = ' ['
            self.text_widget.insert(f"{pos[0]}.{pos[1]}", text, self.PIPE_TAG)

    def _propagate_tags_to_pipes(self) -> None:
        """Extend annotation tags onto pipe delimiters and adjacent whitespace.

        For each pipe range, find the adjacent annotated character (inside the
        bracketed span) and copy its annotation tags onto the pipe characters
        **plus** any whitespace between the pipe and the neighbouring text, so
        the highlight is visually continuous.
        """
        annotation_prefixes = ('lbl_', 'combo_')
        pipe_ranges = self.text_widget.tag_ranges(self.PIPE_TAG)
        for i in range(0, len(pipe_ranges), 2):
            r_start = str(pipe_ranges[i])
            r_end = str(pipe_ranges[i + 1])
            content = self.text_widget.get(r_start, r_end)

            if '[' in content:
                # Inherit tags from the character right after the bracket
                # and extend backward to cover whitespace before it.
                ext_start = r_start
                while True:
                    prev = self.text_widget.index(f"{ext_start}-1c")
                    if prev == ext_start:
                        break
                    ch = self.text_widget.get(prev, ext_start)
                    if ch.isspace() and ch != '\n':
                        ext_start = prev
                    else:
                        break
                for tag in self.text_widget.tag_names(r_end):
                    if tag.startswith(annotation_prefixes) or tag == self.MULTI_LABEL_TAG:
                        self.text_widget.tag_add(tag, ext_start, r_end)

            if ']' in content:
                # Inherit tags from the character right before the bracket
                # and extend forward to cover whitespace after it.
                ext_end = r_end
                while True:
                    ch = self.text_widget.get(ext_end, f"{ext_end}+1c")
                    if ch.isspace() and ch != '\n':
                        ext_end = self.text_widget.index(f"{ext_end}+1c")
                    else:
                        break
                for tag in self.text_widget.tag_names(f"{r_start}-1c"):
                    if tag.startswith(annotation_prefixes) or tag == self.MULTI_LABEL_TAG:
                        self.text_widget.tag_add(tag, r_start, ext_end)

    # ------------------------------------------------------------------
    # Mouse selection → token-snapping
    # ------------------------------------------------------------------

    def _on_mouse_click(self, event: tk.Event) -> None:
        """Clear stored span on a fresh click and record the drag anchor."""
        self.current_span = None
        self._drag_anchor = self.text_widget.index(f"@{event.x},{event.y}")
        self.text_widget.config(selectbackground=self.SELECT_DEFAULT_BG)

    def _on_mouse_release(self, _event: tk.Event) -> None:
        """Schedule snap after the Text widget finishes updating the selection."""
        self.root.after(15, self._snap_selection)

    def _on_mouse_motion(self, event: tk.Event) -> None:
        """Update the cursor-position tag box as the mouse moves over the text."""
        if self.token_map is None:
            return
        if self.current_span is not None:
            return  # Selection is active; box is managed by _restore_selection
        tk_index = self.text_widget.index(f"@{event.x},{event.y}")
        tk_line_i, tk_char_i = [int(x) for x in tk_index.split('.')]
        slate_line = tk_line_i - 1
        adj_char = self._strip_pipe_offset(tk_line_i, tk_char_i)
        token = self.token_map.char_to_token(slate_line, adj_char)
        if token is None:
            self._update_cursor_tags([])
            return
        names = []
        for ann in self.annotation_set.annotations:
            if ann.overlaps_span(slate_line, token, token):
                for internal in sorted(ann.labels):
                    lc = self.config.internal_to_config.get(internal)
                    names.append(lc.name if lc else internal.removeprefix('label:'))
        self._update_cursor_tags(names)

    def _update_cursor_tags(self, names: list) -> None:
        """Update the cursor-position tag box without resizing the status bar."""
        if names:
            self.cursor_tags_var.set('  '.join(names))
            self.cursor_tags_label.config(relief='groove')
        else:
            self.cursor_tags_var.set('')
            self.cursor_tags_label.config(relief='flat')

    def _snap_selection(self) -> None:
        """
        Read the current tkinter selection, snap to token boundaries, and
        store the result in self.current_span.
        """
        if self.token_map is None:
            return

        try:
            raw_start = self.text_widget.index('sel.first')
            raw_end   = self.text_widget.index('sel.last')
        except tk.TclError:
            # No selection
            self.current_span = None
            return

        # --- Parse tkinter indices (1-indexed lines) ----------------------
        start_tk_line, start_tk_char = [int(x) for x in raw_start.split('.')]
        end_tk_line,   end_tk_char   = [int(x) for x in raw_end.split('.')]

        start_sl = start_tk_line - 1   # slate 0-indexed line
        end_sl   = end_tk_line   - 1

        # If sel.last is at char 0 of a line, the selection actually ends
        # just before that line (i.e. at the end of the previous line).
        if end_tk_char == 0 and end_sl > 0:
            end_sl -= 1
            end_tk_char = len(self.token_map.raw_lines[end_sl])

        # Subtract any pipe-delimiter characters inserted before each position
        # so that the offsets match the original text that TokenMap knows about.
        start_tk_char = self._strip_pipe_offset(start_tk_line, start_tk_char)
        end_tk_char   = self._strip_pipe_offset(end_tk_line,   end_tk_char)

        # --- Determine drag direction from stored anchor -------------------
        # Anchor is at sel.first for L→R drags, sel.last for R→L drags.
        anchor = getattr(self, '_drag_anchor', None)
        ltr = True  # default: left-to-right
        if anchor:
            try:
                ltr = self.text_widget.compare(anchor, '<=', raw_end)
            except tk.TclError:
                pass

        # --- Resolve tokens -----------------------------------------------
        # sel.last is exclusive, so subtract 1 to get the actual last char.
        # L→R: floor-snap the end (don't overshoot right into the next token).
        # R→L: ceiling-snap the start (don't overshoot left into the prev token).
        if ltr:
            start_tok = self.token_map.char_to_token(start_sl, start_tk_char, snap='nearest')
            end_tok   = self.token_map.char_to_token(end_sl, max(0, end_tk_char - 1), snap='floor')
        else:
            start_tok = self.token_map.char_to_token(start_sl, start_tk_char, snap='ceiling')
            end_tok   = self.token_map.char_to_token(end_sl, max(0, end_tk_char - 1), snap='nearest')

        # If the start line has no tokens, advance to the next line that does
        if start_tok is None:
            for ln in range(start_sl, self.token_map.num_lines()):
                if self.token_map.num_tokens(ln) > 0:
                    start_sl  = ln
                    start_tok = 0
                    break
            else:
                self.current_span = None
                return

        # If the end line has no tokens, retreat to the previous line that does
        if end_tok is None:
            for ln in range(end_sl, -1, -1):
                if self.token_map.num_tokens(ln) > 0:
                    end_sl  = ln
                    end_tok = self.token_map.num_tokens(ln) - 1
                    break
            else:
                self.current_span = None
                return

        # Normalise so start ≤ end
        if end_sl < start_sl or (end_sl == start_sl and end_tok < start_tok):
            start_sl, end_sl     = end_sl, start_sl
            start_tok, end_tok   = end_tok, start_tok

        self.current_span = (start_sl, start_tok, end_sl, end_tok)

        # --- Update visual selection to full token boundaries -------------
        start_cr = self.token_map.token_char_range(start_sl, start_tok)
        end_cr   = self.token_map.token_char_range(end_sl,   end_tok)
        if start_cr and end_cr:
            adj_start = self._add_pipe_offset(start_sl + 1, start_cr[0])
            adj_end   = self._add_pipe_offset(end_sl   + 1, end_cr[1] + 1)
            tk_sel_start = f"{start_sl + 1}.{adj_start}"
            tk_sel_end   = f"{end_sl   + 1}.{adj_end}"
            self.text_widget.tag_remove('sel', '1.0', 'end')
            self.text_widget.tag_add('sel', tk_sel_start, tk_sel_end)

        # Update status bar
        if start_sl == end_sl:
            span_desc = f"line {start_sl}, token {start_tok}–{end_tok}"
        else:
            span_desc = (
                f"line {start_sl} tok {start_tok} → "
                f"line {end_sl} tok {end_tok}"
            )
        self.status_var.set(f"Selected: {span_desc}   (press a label key to annotate)")
        self._update_cursor_tags(self._labels_in_selection())

    # ------------------------------------------------------------------
    # Label application
    # ------------------------------------------------------------------

    def _apply_label(self, lc: LabelConfig) -> None:
        """Apply (or toggle) *lc* on the current snapped selection."""
        if self.current_span is None:
            self.status_var.set(
                f"Select some text first, then press [{lc.key}] to apply '{lc.name}'"
            )
            return

        start_sl, start_tok, end_sl, end_tok = self.current_span

        # Save undo snapshot before mutating
        self.undo_stack.append(self.annotation_set.copy())

        # Mutual-exclusion: if this label belongs to a group, remove any
        # other labels from the same group on tokens covered by the span.
        if lc.group and lc.group in self.config.groups:
            rivals = self.config.groups[lc.group] - {lc.internal}
            if rivals:
                for ann in list(self.annotation_set.annotations):
                    if ann.overlaps_span_range(start_sl, start_tok, end_sl, end_tok):
                        removed = ann.labels & rivals
                        if removed:
                            ann.labels -= removed
                            if not ann.labels:
                                self.annotation_set.annotations.remove(ann)

        added = self.annotation_set.toggle_label(
            start_sl, start_tok, end_tok, lc.internal,
            end_line=end_sl if start_sl != end_sl else None,
        )
        action = 'Added' if added else 'Removed'

        self._redraw_annotations()
        self.has_unsaved = True
        self.text_widget.config(selectbackground=self.SELECT_LABELLED_BG)
        self._restore_selection()
        self.status_var.set(f"{action} label '{lc.name}' [{lc.key}]")

    # ------------------------------------------------------------------
    # Remove-all action ('u')
    # ------------------------------------------------------------------

    def _remove_selected_annotations(self) -> None:
        """Remove every annotation that overlaps the current selection."""
        if self.current_span is None:
            self.status_var.set("Select text first, then press 'u' to remove annotations")
            return

        start_sl, start_tok, end_sl, end_tok = self.current_span
        self.undo_stack.append(self.annotation_set.copy())
        self.annotation_set.remove_overlapping_range(
            start_sl, start_tok, end_sl, end_tok
        )

        self._redraw_annotations()
        self.has_unsaved = True
        self._clear_selection()
        self.status_var.set("Removed all annotations on selected span")

    # ------------------------------------------------------------------
    # Undo
    # ------------------------------------------------------------------

    def _undo(self) -> None:
        if not self.undo_stack:
            self.status_var.set("Nothing to undo")
            return
        self.annotation_set = self.undo_stack.pop()
        self._redraw_annotations()
        self.has_unsaved = True
        self.status_var.set("Undone")

    # ------------------------------------------------------------------
    # Clear selection
    # ------------------------------------------------------------------

    def _clear_selection(self) -> None:
        self.text_widget.tag_remove('sel', '1.0', 'end')
        self.current_span = None
        self._update_cursor_tags([])

    def _restore_selection(self) -> None:
        """Re-apply the visual 'sel' highlight from current_span after a redraw."""
        if self.current_span is None:
            return
        start_sl, start_tok, end_sl, end_tok = self.current_span
        start_cr = self.token_map.token_char_range(start_sl, start_tok)
        end_cr   = self.token_map.token_char_range(end_sl,   end_tok)
        if start_cr and end_cr:
            adj_start = self._add_pipe_offset(start_sl + 1, start_cr[0])
            adj_end   = self._add_pipe_offset(end_sl   + 1, end_cr[1] + 1)
            tk_sel_start = f"{start_sl + 1}.{adj_start}"
            tk_sel_end   = f"{end_sl   + 1}.{adj_end}"
            self.text_widget.tag_remove('sel', '1.0', 'end')
            self.text_widget.tag_add('sel', tk_sel_start, tk_sel_end)
            self.text_widget.tag_raise('sel')
        self._update_cursor_tags(self._labels_in_selection())

    def _labels_in_selection(self) -> list:
        """Return sorted display names of all labels covering the current span."""
        if self.current_span is None:
            return []
        start_sl, start_tok, end_sl, end_tok = self.current_span
        seen = set()
        names = []
        for ann in self.annotation_set.annotations:
            if ann.overlaps_span_range(start_sl, start_tok, end_sl, end_tok):
                for internal in sorted(ann.labels):
                    if internal not in seen:
                        seen.add(internal)
                        lc = self.config.internal_to_config.get(internal)
                        names.append(lc.name if lc else internal.removeprefix('label:'))
        return names

    # ------------------------------------------------------------------
    # Save / navigate
    # ------------------------------------------------------------------

    def _save_current(self) -> None:
        if not self.files:
            return
        filepath  = self.files[self.current_idx]
        ann_path  = self._annotation_path(filepath)
        try:
            self.annotation_set.save(ann_path)
            self.has_unsaved = False
            self.status_var.set(f"Saved → {os.path.basename(ann_path)}")
        except OSError as exc:
            messagebox.showerror("Save Error", f"Could not save:\n{exc}")

    def _go_next(self) -> None:
        if self.current_idx >= len(self.files) - 1:
            self.status_var.set("Already at the last file")
            return
        self._save_current()
        self._load_file(self.current_idx + 1)

    def _go_prev(self) -> None:
        if self.current_idx <= 0:
            self.status_var.set("Already at the first file")
            return
        self._save_current()
        self._load_file(self.current_idx - 1)

    def _show_help(self) -> None:
        """Open a modal help window with keyboard shortcut reference."""
        win = tk.Toplevel(self.root)
        win.title("Help — Keyboard Shortcuts")
        win.geometry("520x420")
        win.resizable(False, False)
        win.configure(bg='#2c3e50')

        label_lines = '\n'.join(
            f"  [{lc.key}]            Apply / toggle label '{lc.name}'"
            for lc in self.config.labels.values()
        )

        help_text = (
            "Annotation Tool — Keyboard Shortcuts\n"
            "─────────────────────────────────────\n\n"
            "Navigation\n"
            "  [   (left bracket)    Previous file\n"
            "  ]   (right bracket)   Next file\n\n"
            "File\n"
            "  Ctrl+S               Save current file\n"
            "  Ctrl+Q               Quit\n\n"
            "Annotation\n"
            f"{label_lines}\n"
            "  u                    Remove all annotations on selection\n"
            "  Ctrl+Z               Undo last action\n"
            "  Escape               Clear current selection\n\n"
            "Usage\n"
            "  1. Click and drag to select text.\n"
            "  2. Press a label key to annotate the selection.\n"
            "  3. Re-selecting the same span and pressing the same\n"
            "     label key toggles (removes) that label.\n"
            "  4. Annotations are saved automatically when\n"
            "     navigating between files.\n"
        )

        txt = tk.Text(
            win, wrap='word', bg='#2c3e50', fg='white',
            font=('Courier', 11), padx=16, pady=12,
            relief='flat', state='normal', cursor='arrow',
        )
        txt.insert('1.0', help_text)
        txt.config(state='disabled')
        txt.pack(fill='both', expand=True, padx=8, pady=(8, 0))

        def _close_help():
            win.destroy()
            self.root.focus_force()
            self.text_widget.focus_set()

        tk.Button(
            win, text='Close', command=_close_help,
            bg='#34495e', fg='black', activebackground='#4a6278',
            activeforeground='black', relief='flat',
            padx=14, pady=5, font=('Helvetica', 11),
        ).pack(pady=10)

        win.protocol('WM_DELETE_WINDOW', _close_help)

    def _change_font_size(self, delta: int) -> None:
        """Increase or decrease the text area font size by *delta* points."""
        new_size = max(6, min(40, self.font_size + delta))
        if new_size == self.font_size:
            return
        self.font_size = new_size
        self.text_widget.config(font=('Helvetica', self.font_size))
        # Reconfigure style-based tags with the new size
        self._configure_tags()
        # Invalidate combo-tag cache so they are rebuilt at the new size
        self._combo_tags.clear()
        if self.token_map is not None:
            self._redraw_annotations()

    def _quit(self) -> None:
        if self.has_unsaved:
            answer = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes.\nSave before quitting?",
            )
            if answer is None:   # Cancel
                return
            if answer:           # Yes
                self._save_current()
        self.root.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_app(
    config: Config,
    files: List[str],
    output_dir: Optional[str],
    annotator: str,
) -> None:
    root = tk.Tk()
    _app = AnnotationApp(root, config, files, output_dir, annotator)
    root.mainloop()
