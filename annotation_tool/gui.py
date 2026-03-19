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
import tkinter as tk
from tkinter import messagebox
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

    def __init__(
        self,
        root: tk.Tk,
        config: Config,
        files: List[str],
        output_dir: Optional[str],
        annotator: str,
        resume: bool,
    ) -> None:
        self.root = root
        self.config = config
        self.files = files
        self.output_dir = output_dir
        self.annotator = annotator
        self.resume = resume

        self.current_idx: int = 0
        self.token_map: Optional[TokenMap] = None
        self.annotation_set = AnnotationSet()
        self.undo_stack: List[AnnotationSet] = []
        self.has_unsaved: bool = False

        # The snapped selection: (start_line, start_tok, end_line, end_tok) — all 0-indexed
        self.current_span: Optional[Tuple[int, int, int, int]] = None

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
        self.status_var = tk.StringVar(value='Ready')
        status_bar = tk.Label(
            self.root, textvariable=self.status_var,
            anchor='w', bg='#bdc3c7', fg='#2c3e50',
            font=('Helvetica', 10), padx=10, pady=3,
        )
        status_bar.pack(fill='x', side='bottom')

        # ── Legend panel ──────────────────────────────────────────────
        legend_frame = tk.Frame(self.root, bg='#ecf0f1', relief='groove', bd=1)
        legend_frame.pack(fill='x', side='bottom', padx=0, pady=0)

        tk.Label(
            legend_frame, text='Labels:', bg='#ecf0f1',
            font=('Helvetica', 10, 'bold'), padx=8, pady=5,
        ).pack(side='left')

        for lc in self.config.labels.values():
            cell = tk.Frame(legend_frame, bg='#ecf0f1', padx=4, pady=4)
            cell.pack(side='left')
            tk.Label(
                cell, text=f'[{lc.key}]', bg='#ecf0f1',
                font=('Courier', 10, 'bold'), fg='#2c3e50',
            ).pack(side='left')
            tk.Label(
                cell,
                text=f' {lc.name} ',
                bg=lc.colour,
                fg=_contrast(lc.colour),
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
            text=' multi ',
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
            font=('Helvetica', 13),
            yscrollcommand=scrollbar.set,
            # Keep 'normal' so we can intercept key events reliably;
            # all text-modification keys are blocked in _on_key_press.
            state='normal',
            cursor='xterm',
            padx=16, pady=12,
            spacing1=4, spacing2=2, spacing3=4,
            selectbackground='#aed6f1',
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
        cmd    = bool(event.state & 0x8)   # Command (macOS) held

        # --- Ctrl / Cmd shortcuts ----------------------------------------
        if ctrl or cmd:
            k = keysym.lower()
            if k == 's':
                self._save_current()
            elif k == 'z':
                self._undo()
            elif k == 'q':
                self._quit()
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

        # Remove existing annotation tags
        for lc in self.config.labels.values():
            self.text_widget.tag_remove(lc.tag, '1.0', 'end')
        self.text_widget.tag_remove(self.MULTI_LABEL_TAG, '1.0', 'end')

        # Build per-token label sets: (slate_line, token) → set of internal label names
        pos_labels: dict = {}
        for ann in self.annotation_set.annotations:
            if not ann.labels:
                continue
            for tok in range(ann.start_token, ann.end_token + 1):
                key = (ann.line, tok)
                if key not in pos_labels:
                    pos_labels[key] = set()
                pos_labels[key].update(ann.labels)

        # Resolve each token position to a tag name
        line_tok_tags: dict = {}  # slate_line → {token: tag_name}
        for (sl, tok), labels in pos_labels.items():
            if sl not in line_tok_tags:
                line_tok_tags[sl] = {}
            if len(labels) == 1:
                internal = next(iter(labels))
                lc = self.config.internal_to_config.get(internal)
                if lc:
                    line_tok_tags[sl][tok] = lc.tag
            else:
                line_tok_tags[sl][tok] = self.MULTI_LABEL_TAG

        # Apply tags, merging contiguous runs of the same tag to fill gaps
        for sl, tok_tags in line_tok_tags.items():
            sorted_toks = sorted(tok_tags.keys())
            if not sorted_toks:
                continue
            run_start = sorted_toks[0]
            run_tag = tok_tags[run_start]
            prev = run_start
            for tok in sorted_toks[1:]:
                cur_tag = tok_tags[tok]
                if tok == prev + 1 and cur_tag == run_tag:
                    prev = tok
                else:
                    self._apply_tag_run(sl, run_start, prev, run_tag)
                    run_start, run_tag, prev = tok, cur_tag, tok
            self._apply_tag_run(sl, run_start, prev, run_tag)

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

    # ------------------------------------------------------------------
    # Mouse selection → token-snapping
    # ------------------------------------------------------------------

    def _on_mouse_click(self, _event: tk.Event) -> None:
        """Clear stored span on a fresh click."""
        self.current_span = None

    def _on_mouse_release(self, _event: tk.Event) -> None:
        """Schedule snap after the Text widget finishes updating the selection."""
        self.root.after(15, self._snap_selection)

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

        # --- Resolve tokens -----------------------------------------------
        start_tok = self.token_map.char_to_token(start_sl, start_tk_char)
        end_tok   = self.token_map.char_to_token(end_sl,   end_tk_char)

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
            tk_sel_start = f"{start_sl + 1}.{start_cr[0]}"
            tk_sel_end   = f"{end_sl   + 1}.{end_cr[1] + 1}"
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

        if start_sl == end_sl:
            # Single-line toggle
            added = self.annotation_set.toggle_label(
                start_sl, start_tok, end_tok, lc.internal
            )
            action = 'Added' if added else 'Removed'
        else:
            # Multi-line: determine global toggle direction.
            # If ALL per-line spans already carry the label → remove;
            # otherwise → add everywhere.
            all_have = self._multiline_all_have(
                start_sl, start_tok, end_sl, end_tok, lc.internal
            )

            for line in range(start_sl, end_sl + 1):
                n = self.token_map.num_tokens(line)
                if n == 0:
                    continue
                if line == start_sl:
                    s, e = start_tok, n - 1
                elif line == end_sl:
                    s, e = 0, end_tok
                else:
                    s, e = 0, n - 1

                if all_have:
                    # Remove the label from this span
                    ann = self.annotation_set.get_at_span(line, s, e)
                    if ann and lc.internal in ann.labels:
                        ann.labels.discard(lc.internal)
                        if not ann.labels:
                            self.annotation_set.annotations.remove(ann)
                else:
                    # Add if not present; use toggle which will add
                    existing = self.annotation_set.get_at_span(line, s, e)
                    if existing is None or lc.internal not in existing.labels:
                        self.annotation_set.toggle_label(line, s, e, lc.internal)

            action = 'Removed' if all_have else 'Applied'

        self._redraw_annotations()
        self.has_unsaved = True
        self._clear_selection()
        self.status_var.set(f"{action} label '{lc.name}' [{lc.key}]")

    def _multiline_all_have(
        self,
        start_sl: int, start_tok: int,
        end_sl: int,   end_tok: int,
        label: str,
    ) -> bool:
        """Return True if every per-line span in the selection already has *label*."""
        for line in range(start_sl, end_sl + 1):
            n = self.token_map.num_tokens(line)
            if n == 0:
                continue
            if line == start_sl:
                s, e = start_tok, n - 1
            elif line == end_sl:
                s, e = 0, end_tok
            else:
                s, e = 0, n - 1
            ann = self.annotation_set.get_at_span(line, s, e)
            if ann is None or label not in ann.labels:
                return False
        return True

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

        for line in range(start_sl, end_sl + 1):
            n = self.token_map.num_tokens(line)
            if n == 0:
                continue
            if line == start_sl and line == end_sl:
                s, e = start_tok, end_tok
            elif line == start_sl:
                s, e = start_tok, n - 1
            elif line == end_sl:
                s, e = 0, end_tok
            else:
                s, e = 0, n - 1
            self.annotation_set.remove_overlapping(line, s, e)

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
    resume: bool,
) -> None:
    root = tk.Tk()
    _app = AnnotationApp(root, config, files, output_dir, annotator, resume)
    root.mainloop()
