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

import itertools
import os
import sys
import tkinter as tk
from tkinter import messagebox
import tkinter.font as tkfont
from typing import List, Optional, Tuple

from .config import Config, LabelConfig
from .data import (
    ADJUDICATION_NAME, ANNOTATION_SUFFIX, AnnotationSet, TokenMap,
    compute_adjudication, read_text,
)


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
    DISAGREEMENT_TAG   = '_disagreement'
    DISAGREEMENT_COLOUR = '#e74c3c'
    SELECT_DEFAULT_BG  = '#aed6f1'
    SELECT_LABELLED_BG = '#a8e6cf'

    def __init__(
        self,
        root: tk.Tk,
        config: Config,
        files: List[str],
        output_dir: Optional[str],
        annotator: str,
        adjudication_annotators: Optional[List[tuple]] = None,
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
        # Widget indices where the mouse was pressed and released, used to
        # tell left-to-right drags from right-to-left ones.
        self._drag_anchor: Optional[str] = None
        self._drag_release: Optional[str] = None

        # Font size for the text area (adjustable at runtime)
        self.font_size: int = 13

        # The layer (group) shown and edited now; None when the config has
        # no Layers: line, so every label is shown
        self._active_layer: Optional[str] = (
            config.layers[0] if config.layers else None
        )

        # Cache for composite style tags (used when multiple style labels overlap)
        self._combo_tags: dict = {}
        self._combo_ids = itertools.count()   # never reused, so names can't clash

        # Adjudication mode
        self._adjudication_mode: bool = adjudication_annotators is not None
        self._adjudication_annotators: list = adjudication_annotators or []
        self._annotator_names: List[str] = [
            name for name, _ in self._adjudication_annotators
        ]
        # group → token positions where annotators disagree (see compute_adjudication)
        self._disagreement_positions: dict = {}
        self._token_annotator_info: dict = {}
        self._viewing_annotator: Optional[str] = None
        self._saved_annotation_set: Optional[AnnotationSet] = None
        self._annotator_sets_cache: dict = {}  # name → AnnotationSet for current file
        # Annotators with no annotations on the current file (left out of the comparison)
        self._empty_annotators: List[str] = []

        self._build_ui()
        self._astral_width = self._measure_astral_width()
        self._configure_tags()
        self._bind_keys()
        self._load_first_available(range(len(self.files)))

    def _measure_astral_width(self) -> int:
        """How many Tk index positions one emoji (non-BMP character) occupies.

        Tk 9 counts it as one character; Tk 8.6 as two (a UTF-16 surrogate
        pair); older builds can differ again — so measure rather than assume.
        """
        probe = tk.Text(self.root)
        try:
            probe.insert('1.0', '\U0001F600')
            return int(probe.index('1.end').split('.')[1]) or 1
        except tk.TclError:
            return 1
        finally:
            probe.destroy()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        if self._adjudication_mode:
            self.root.title("Adjudication Tool")
        else:
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

        # ── View-annotator dropdown (adjudication mode only) ──────
        if self._adjudication_mode:
            self._view_var = tk.StringVar(value='Adjudication')
            choices = ['Adjudication'] + self._annotator_names
            self._view_menu = tk.OptionMenu(
                hdr, self._view_var, *choices,
                command=self._on_view_changed,
            )
            self._view_menu.config(
                bg='#34495e', fg='black', activebackground='#4a6278',
                activeforeground='black', relief='flat', padx=6, pady=3,
                font=('Helvetica', 11), highlightthickness=0,
            )
            self._view_menu.pack(side='left', padx=6)

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
        self._legend_frame = tk.Frame(self.root, bg='#ecf0f1', relief='groove', bd=1)
        self._legend_frame.pack(fill='x', side='bottom', padx=0, pady=0)
        self._build_legend()

        # ── View banner (adjudication mode — shown when viewing an annotator) ──
        if self._adjudication_mode:
            self._view_banner = tk.Frame(self.root, bg='#f39c12', padx=8, pady=6)
            # Not packed yet — shown/hidden dynamically
            self._view_banner_var = tk.StringVar(value='')
            lbl = tk.Label(
                self._view_banner, textvariable=self._view_banner_var,
                bg='#f39c12', fg='white',
                font=('Helvetica', 11, 'bold'), padx=10, pady=2,
                cursor='hand2',
            )
            lbl.pack(fill='x')
            lbl.bind('<Button-1>', lambda e: self._return_to_adjudication())

            # Notice naming annotators who made no annotations on this file
            self._notice_bar = tk.Frame(self.root, bg='#fcf3cf', padx=8, pady=4)
            self._notice_var = tk.StringVar(value='')
            tk.Label(
                self._notice_bar, textvariable=self._notice_var,
                bg='#fcf3cf', fg='#7d6608', anchor='w', justify='left',
                font=('Helvetica', 11), padx=10, pady=2,
            ).pack(fill='x')

        # ── Text area ─────────────────────────────────────────────────
        self._text_outer = tk.Frame(self.root, bg='white')
        self._text_outer.pack(fill='both', expand=True, padx=0, pady=0)

        scrollbar = tk.Scrollbar(self._text_outer)
        scrollbar.pack(side='right', fill='y')

        self.text_widget = tk.Text(
            self._text_outer,
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

        # ── Annotator info overlay (adjudication mode, bottom-right of text area)
        if self._adjudication_mode:
            self._ann_info_frame = tk.Frame(
                self._text_outer, bg='#2c3e50', padx=8, pady=6,
                relief='solid', bd=1,
            )
            self._ann_info_label = tk.Label(
                self._ann_info_frame, text='',
                bg='#2c3e50', fg='white', justify='left', anchor='w',
                font=('Helvetica', self.font_size), padx=4, pady=2,
            )
            self._ann_info_label.pack()
            # Hidden by default; placed when there is info to show
            self._ann_info_visible = False
            self._text_outer.bind('<Configure>', self._reposition_ann_info)

    def _build_legend(self) -> None:
        """Fill the legend with the active layer (if any) and the labels shown."""
        legend_frame = self._legend_frame
        for child in legend_frame.winfo_children():
            child.destroy()

        if self._active_layer is not None:
            tk.Label(
                legend_frame, text='Layer:', bg='#ecf0f1', fg='black',
                font=('Helvetica', 10, 'bold'), padx=8, pady=5,
            ).pack(side='left')
            tk.Label(
                legend_frame, text=f' {self._active_layer} ',
                bg='#2c3e50', fg='white', font=('Helvetica', 10, 'bold'),
                relief='flat', padx=4, pady=2,
            ).pack(side='left')
            tk.Label(
                legend_frame, text='(Tab to switch)', bg='#ecf0f1', fg='#7f8c8d',
                font=('Helvetica', 10), padx=4, pady=5,
            ).pack(side='left', padx=(0, 8))

        tk.Label(
            legend_frame, text='Labels:', bg='#ecf0f1', fg='black',
            font=('Helvetica', 10, 'bold'), padx=8, pady=5,
        ).pack(side='left')

        for lc in self.config.labels.values():
            if not self._is_shown(lc.internal):
                continue
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

    # ------------------------------------------------------------------
    # Layers
    # ------------------------------------------------------------------

    def _label_group(self, internal: str) -> Optional[str]:
        """The group of *internal* (None if it has none or isn't in the config)."""
        lc = self.config.internal_to_config.get(internal)
        return lc.group if lc else None

    def _group_shown(self, group: Optional[str]) -> bool:
        """Whether labels in *group* are drawn and editable right now.

        Without layers everything is.  With layers, a layer's labels are
        shown only while it is active; every other group (and None, for
        labels with no group or unknown to the config) is always shown.
        """
        return (self._active_layer is None
                or group not in self.config.layers
                or group == self._active_layer)

    def _is_shown(self, internal: str) -> bool:
        return self._group_shown(self._label_group(internal))

    def _shown(self, labels: set) -> set:
        """The labels in *labels* that are shown right now."""
        return {internal for internal in labels if self._is_shown(internal)}

    def _switch_layer(self, step: int) -> None:
        """Show the layer *step* places after the active one (wrapping round)."""
        layers = self.config.layers
        idx = layers.index(self._active_layer)
        self._active_layer = layers[(idx + step) % len(layers)]
        self._build_legend()
        if self.token_map is not None:
            self._redraw_annotations()
            self._restore_selection()
        self.status_var.set(
            f"Showing the {self._active_layer} layer (Tab to switch)"
        )

    def _reposition_ann_info(self, _event=None) -> None:
        """Keep the annotator info overlay anchored to the bottom-right."""
        if not self._adjudication_mode or not self._ann_info_visible:
            return
        self._ann_info_frame.update_idletasks()
        fw = self._ann_info_frame.winfo_reqwidth()
        fh = self._ann_info_frame.winfo_reqheight()
        pw = self._text_outer.winfo_width()
        ph = self._text_outer.winfo_height()
        x = pw - fw - 20   # 20px from right edge (room for scrollbar)
        y = ph - fh - 8
        self._ann_info_frame.place(x=max(0, x), y=max(0, y))

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
        # Disagreement highlight (adjudication mode)
        if self._adjudication_mode:
            self.text_widget.tag_configure(
                self.DISAGREEMENT_TAG,
                background=self.DISAGREEMENT_COLOUR,
                foreground='white',
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
        self.text_widget.bind('<Leave>', self._on_mouse_leave)

        # The widget stays in 'normal' state so it receives key events, so
        # also block the other ways Tk can edit it: a middle-click pastes the
        # selection, and on macOS the press-and-hold accent menu / input
        # methods send events that delete text (Tk 8.6+).
        #
        # Don't add <<Undo>>/<<Redo>> here: a virtual event tied to a specific
        # key outranks the catch-all <Key> binding, so binding it would
        # swallow Ctrl/Cmd+Z before _on_key_press could undo.  The same rule
        # is why <<Copy>> is bound to our own copy handler.
        for seq in ('<<Paste>>', '<<PasteSelection>>', '<<Cut>>', '<<Clear>>',
                    '<<TkAccentBackspace>>', '<<TkStartIMEMarkedText>>',
                    '<<TkEndIMEMarkedText>>', '<<TkClearIMEMarkedText>>'):
            self.text_widget.bind(seq, lambda _e: 'break')
        self.text_widget.bind('<<Copy>>', self._copy_selection)

        # Window close
        self.root.protocol('WM_DELETE_WINDOW', self._quit)
        # macOS: the app menu's Quit item (and Cmd+Q) bypass WM_DELETE_WINDOW
        # and exit immediately unless this handler is defined.
        if self.root.tk.call('tk', 'windowingsystem') == 'aqua':
            self.root.tk.createcommand('::tk::mac::Quit', self._quit)

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

        # Windows reports AltGr as Ctrl+Alt (Alt = 0x20000), so a printable
        # character typed with AltGr (e.g. '[' or ']' on German keyboards)
        # is an ordinary key, not a Ctrl shortcut.
        if (ctrl and sys.platform == 'win32' and event.state & 0x20000
                and char and char.isprintable()):
            ctrl = False

        # With Caps Lock on, letter keys arrive in upper case; fall back to
        # the lower-case key unless the upper-case one is itself a label.
        if event.state & 0x2 and char and char not in self.config.labels:
            char = char.lower()

        # --- Ctrl / Cmd shortcuts ----------------------------------------
        if ctrl or cmd:
            k = keysym.lower()
            if k == 's' and not self._viewing_annotator:
                self._save_current()
            elif k == 'z' and not self._viewing_annotator:
                self._undo()
            elif k == 'q':
                self._quit()
            elif k in ('equal', 'plus'):
                self._change_font_size(1)
            elif k == 'minus':
                self._change_font_size(-1)
            elif k == 'c':
                self._copy_selection()
            elif k == 'a':
                # Select all ourselves: Tk's own Ctrl+A moves to the line
                # start on Linux and older Tk.  Then snap so the stored span
                # matches what is now selected.
                self.text_widget.tag_add('sel', '1.0', 'end-1c')
                self._drag_anchor = self._drag_release = None
                self._snap_selection()
            return 'break'

        # --- Escape ----------------------------------------------------------
        if keysym == 'Escape':
            if self._viewing_annotator:
                self._return_to_adjudication()
            else:
                self._clear_selection()
            return 'break'

        # --- Scrolling -------------------------------------------------------
        # Scroll the view directly: Tk's default bindings for these keys move
        # the insert cursor and clear the visible selection, which would leave
        # a label key to act on a span the user can no longer see.
        if self._scroll_for_key(keysym):
            return 'break'

        # --- Switch layer (Tab / Shift+Tab) ----------------------------------
        # Allowed when viewing an annotator: it changes the view, not the data.
        # X11 reports Shift+Tab as ISO_Left_Tab; macOS and Windows as Tab+Shift.
        if keysym in ('Tab', 'ISO_Left_Tab'):
            if self._active_layer is not None:
                back = keysym == 'ISO_Left_Tab' or bool(event.state & 0x1)
                self._switch_layer(-1 if back else 1)
            return 'break'

        # --- Read-only when viewing an annotator ----------------------------
        if self._viewing_annotator:
            return 'break'

        # --- Navigation keys -----------------------------------------------
        if keysym == 'bracketright' or char == ']':
            if not self._viewing_annotator:
                self._go_next()
            return 'break'
        if keysym == 'bracketleft' or char == '[':
            if not self._viewing_annotator:
                self._go_prev()
            return 'break'

        # --- Remove annotations ('u') ----------------------------------------
        if char == 'u' or keysym == 'u':
            self._remove_selected_annotations()
            return 'break'

        # --- Label keys (from config) ----------------------------------------
        if char and char in self.config.labels:
            self._apply_label(self.config.labels[char])
            return 'break'

        # --- Block everything else -------------------------------------------
        return 'break'

    def _selected_original_text(self) -> Optional[str]:
        """The selected text without the inserted [ ] bracket characters."""
        w = self.text_widget
        try:
            first, last = w.index('sel.first'), w.index('sel.last')
        except tk.TclError:
            return None
        parts, pos = [], first
        ranges = w.tag_ranges(self.PIPE_TAG)
        for i in range(0, len(ranges), 2):
            p_start, p_end = str(ranges[i]), str(ranges[i + 1])
            if w.compare(p_end, '<=', first) or w.compare(p_start, '>=', last):
                continue
            if w.compare(p_start, '>', pos):
                parts.append(w.get(pos, p_start))
            pos = p_end if w.compare(p_end, '<', last) else last
        if w.compare(pos, '<', last):
            parts.append(w.get(pos, last))
        return ''.join(parts)

    def _copy_selection(self, _event=None) -> str:
        """Copy the selection to the clipboard, minus the bracket characters."""
        text = self._selected_original_text()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        return 'break'

    _SCROLL_KEYS = {
        'Up': (-1, 'units'), 'Down': (1, 'units'),
        'Prior': (-1, 'pages'), 'Next': (1, 'pages'),
    }

    def _scroll_for_key(self, keysym: str) -> bool:
        """Scroll the text for a navigation key; return True if handled."""
        keysym = keysym[3:] if keysym.startswith('KP_') else keysym
        if keysym in self._SCROLL_KEYS:
            amount, what = self._SCROLL_KEYS[keysym]
            self.text_widget.yview_scroll(amount, what)
        elif keysym == 'Home':
            self.text_widget.yview_moveto(0.0)
        elif keysym == 'End':
            self.text_widget.yview_moveto(1.0)
        else:
            return False
        return True

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _annotation_path(self, filepath: str) -> str:
        basename = os.path.basename(filepath)
        if self._adjudication_mode:
            ann_filename = f"{basename}.{ADJUDICATION_NAME}{ANNOTATION_SUFFIX}"
        elif self.annotator:
            ann_filename = f"{basename}.{self.annotator}{ANNOTATION_SUFFIX}"
        else:
            ann_filename = f"{basename}{ANNOTATION_SUFFIX}"
        if self.output_dir:
            return os.path.join(self.output_dir, ann_filename)
        return os.path.join(os.path.dirname(filepath), ann_filename)

    def _load_first_available(self, indices) -> bool:
        """Load the first file in *indices* that can be opened.

        Files that can't be opened (e.g. an annotation file that isn't
        UTF-8, or a cloud file that fails to download) are skipped and
        reported together, so one bad file doesn't block the rest.
        Returns False, leaving the current file as it was, if none open.
        """
        skipped = []
        for idx in indices:
            err = self._load_file(idx)
            if err is None:
                if skipped:
                    self.status_var.set(f"Skipped {len(skipped)} file(s) that could not be opened")
                    messagebox.showwarning(
                        "Skipped files",
                        "These files could not be opened and were skipped:\n\n"
                        + "\n".join(skipped),
                    )
                return True
            skipped.append(f"{os.path.basename(self.files[idx])}: {err}")
        if skipped:
            self.status_var.set("Could not open " + skipped[0])
            messagebox.showerror(
                "Could not open file",
                "These files could not be opened:\n\n" + "\n".join(skipped),
            )
        return False

    def _load_file(self, idx: int) -> Optional[str]:
        """Load file *idx*.  Return None on success, or an error message
        (leaving the current file as it was) if it or its annotations
        cannot be read."""
        if idx < 0 or idx >= len(self.files):
            return "no such file"

        filepath = self.files[idx]
        basename = os.path.basename(filepath)
        ann_path = self._annotation_path(filepath)

        # Read everything before touching any state, so a failure can't
        # leave current_idx pointing at one file and the annotations of
        # another (the next save would then write them to the wrong file).
        try:
            content = read_text(filepath)
            token_map = TokenMap(content, astral_width=self._astral_width)
            annotation_set = AnnotationSet.load(ann_path)
            annotator_sets = []
            if self._adjudication_mode:
                for name, file_map in self._adjudication_annotators:
                    ann_file = file_map.get(basename)
                    aset = AnnotationSet.load(ann_file) if ann_file else AnnotationSet()
                    annotator_sets.append((name, aset))
        except (OSError, ValueError) as exc:   # UnicodeDecodeError is a ValueError
            return str(exc)

        self.current_idx = idx
        self.token_map = token_map

        # Check the file has at least one token
        total_tokens = sum(
            self.token_map.num_tokens(l)
            for l in range(self.token_map.num_lines())
        )
        if total_tokens == 0:
            self.status_var.set(f"Warning: {basename} appears to be empty.")

        # Load (or reset) annotations
        self.annotation_set = annotation_set
        self.undo_stack.clear()
        self.has_unsaved = False
        self.current_span = None
        self._update_cursor_tags([])

        # Adjudication: load annotator data and compute agreements
        if self._adjudication_mode:
            # Reset view state when navigating files
            self._viewing_annotator = None
            self._saved_annotation_set = None
            if hasattr(self, '_view_var'):
                self._view_var.set('Adjudication')
            if hasattr(self, '_view_banner'):
                self._view_banner.pack_forget()

            self._annotator_sets_cache = dict(annotator_sets)

            # With layers, each group is compared on its own, so disagreeing
            # on one layer of a span doesn't hide agreement on the others.
            agreed, disagreements, details, empty = compute_adjudication(
                annotator_sets, self.token_map,
                partition_of=self._label_group if self.config.layers else None,
            )
            self._disagreement_positions = disagreements
            self._token_annotator_info = details
            self._empty_annotators = empty
            self._update_notice_bar()

            # If no existing adjudication file, start from agreed annotations
            if not os.path.isfile(ann_path):
                self.annotation_set = agreed

        # Populate text widget
        self.text_widget.config(state='normal')
        self.text_widget.delete('1.0', 'end')
        self.text_widget.insert('1.0', content)
        # Keep state='normal' so key events fire; key handler blocks modifications.

        # Draw existing annotations
        self._redraw_annotations()

        # Update header / status
        self._update_header()
        self.status_var.set(f"Loaded: {basename}")
        self.text_widget.focus_set()
        return None

    def _update_notice_bar(self) -> None:
        """Show which annotators made no annotations on the current file."""
        empty = self._empty_annotators
        if not empty:
            self._notice_bar.pack_forget()
            return
        if len(empty) == len(self._annotator_names):
            text = "None of the annotators made any annotations on this document."
        else:
            names = (empty[0] if len(empty) == 1
                     else ', '.join(empty[:-1]) + ' and ' + empty[-1])
            text = (f"{names} made no annotations on this document, "
                    f"so they are left out of the comparison.")
        self._notice_var.set(text)
        self._notice_bar.pack(fill='x', side='top', before=self._text_outer)

    def _update_header(self) -> None:
        filepath = self.files[self.current_idx]
        basename = os.path.basename(filepath)
        if self._adjudication_mode:
            title = f"Adjudication  —  {basename}"
        elif self.annotator:
            title = f"{self.annotator}  —  {basename}"
        else:
            title = basename
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
    # Annotator view switching (adjudication mode)
    # ------------------------------------------------------------------

    def _on_view_changed(self, selection: str) -> None:
        """Handle the view dropdown change."""
        if selection == 'Adjudication':
            self._return_to_adjudication()
        else:
            self._view_annotator(selection)

    def _view_annotator(self, name: str) -> None:
        """Switch to read-only view of a single annotator's annotations."""
        if self.token_map is None:
            return
        # Save current adjudication work if not already saved
        if self._viewing_annotator is None:
            self._saved_annotation_set = self.annotation_set.copy()

        self._viewing_annotator = name
        ann_set = self._annotator_sets_cache.get(name, AnnotationSet())
        self.annotation_set = ann_set

        # Redraw with annotator's annotations (no disagreement highlights)
        self._redraw_annotations()
        self._clear_selection()

        # Show banner
        self._view_banner_var.set(
            f"Looking at {name} Annotations. Click here to return back."
        )
        self._view_banner.pack(fill='x', side='top', before=self._text_outer)

        # Update header
        filepath = self.files[self.current_idx]
        basename = os.path.basename(filepath)
        self.lbl_filename.config(text=f"{name}  \u2014  {basename}")
        self.status_var.set(f"Viewing {name}'s annotations (read-only)")

    def _return_to_adjudication(self) -> None:
        """Return from annotator view back to adjudication editing."""
        if self._viewing_annotator is None:
            return
        self._viewing_annotator = None

        # Restore the adjudicator's working annotations
        if self._saved_annotation_set is not None:
            self.annotation_set = self._saved_annotation_set
            self._saved_annotation_set = None

        # Hide banner
        self._view_banner.pack_forget()

        # Reset dropdown
        self._view_var.set('Adjudication')

        # Redraw with disagreement highlights
        self._redraw_annotations()
        self._clear_selection()

        # Restore header
        self._update_header()
        self.status_var.set("Returned to adjudication")

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
        self.text_widget.tag_remove(self.DISAGREEMENT_TAG, '1.0', 'end')
        for combo_tag in self._combo_tags.values():
            self.text_widget.tag_remove(combo_tag, '1.0', 'end')

        # Build per-token label sets and annotation-identity sets:
        # (slate_line, token) → set of internal label names
        # (slate_line, token) → frozenset of annotation ids (to detect span boundaries)
        pos_labels: dict = {}
        pos_ann_ids: dict = {}
        for ann in self.annotation_set.annotations:
            labels = self._shown(ann.labels)   # hidden layers aren't drawn
            if not labels:
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
                    pos_labels[key].update(labels)
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

        # Disagreement highlights (adjudication mode, not when viewing an annotator)
        if self._adjudication_mode and not self._viewing_annotator:
            self._apply_disagreement_highlights()

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

        tag_name = f'combo_{next(self._combo_ids)}'
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
        """Insert [ ] at the boundaries of styled (bold/italic/underline) spans.

        With layers, every span of the active layer gets them too, whatever
        its display, so neighbouring spans with the same label stay distinct.
        """
        if self.token_map is None:
            return

        bracketed = {
            lc.internal for lc in self.config.labels.values()
            if lc.style or (self._active_layer is not None
                            and lc.group == self._active_layer)
        }
        if not bracketed:
            return

        # Collect open ([) and close (]) positions separately.
        # For multi-line annotations, [ goes on the start line, ] on the end line.
        open_positions: set = set()
        close_positions: set = set()
        for ann in self.annotation_set.annotations:
            if not (self._shown(ann.labels) & bracketed):
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
    # Disagreement highlights (adjudication mode)
    # ------------------------------------------------------------------

    def _apply_disagreement_highlights(self) -> None:
        """Apply red background to the disagreements in the groups shown."""
        if not self._disagreement_positions or self.token_map is None:
            return
        self.text_widget.tag_remove(self.DISAGREEMENT_TAG, '1.0', 'end')

        positions: set = set()
        for group, group_positions in self._disagreement_positions.items():
            if self._group_shown(group):
                positions |= group_positions

        # Group by line and merge consecutive tokens into runs
        by_line: dict = {}
        for (sl, tok) in positions:
            by_line.setdefault(sl, []).append(tok)

        for sl, toks in by_line.items():
            toks.sort()
            runs = []
            run_start = toks[0]
            run_end = toks[0]
            for tok in toks[1:]:
                if tok == run_end + 1:
                    run_end = tok
                else:
                    runs.append((run_start, run_end))
                    run_start = tok
                    run_end = tok
            runs.append((run_start, run_end))

            for start_tok, end_tok in runs:
                rng = self._span_widget_range(sl, start_tok, sl, end_tok)
                if rng:
                    self.text_widget.tag_add(self.DISAGREEMENT_TAG, *rng)

        # Disagreement sits below annotation tags but above default text
        self.text_widget.tag_lower(self.DISAGREEMENT_TAG)

    # ------------------------------------------------------------------
    # Mouse selection → token-snapping
    # ------------------------------------------------------------------

    def _on_mouse_click(self, event: tk.Event) -> None:
        """Clear stored span on a fresh click and record the drag anchor."""
        self.current_span = None
        self._drag_anchor = self.text_widget.index(f"@{event.x},{event.y}")
        self._drag_release = None
        self.text_widget.config(selectbackground=self.SELECT_DEFAULT_BG)

    def _on_mouse_release(self, event: tk.Event) -> None:
        """Record where the drag ended, then snap once the Text widget has
        finished updating the selection."""
        self._drag_release = self.text_widget.index(f"@{event.x},{event.y}")
        self.root.after(15, self._snap_selection)

    def _span_widget_range(
        self, start_sl: int, start_tok: int, end_sl: int, end_tok: int,
    ) -> Optional[Tuple[str, str]]:
        """Widget indices covering tokens start..end, excluding the inserted
        bracket characters just outside them."""
        start_cr = self.token_map.token_char_range(start_sl, start_tok)
        end_cr = self.token_map.token_char_range(end_sl, end_tok)
        if not start_cr or not end_cr:
            return None
        start = self._add_pipe_offset(start_sl + 1, start_cr[0])
        # Map the last character, then step past it: mapping the exclusive
        # end directly would land after a '] ' inserted at that position.
        end = self._add_pipe_offset(end_sl + 1, end_cr[1]) + 1
        return f"{start_sl + 1}.{start}", f"{end_sl + 1}.{end}"

    def _on_mouse_motion(self, event: tk.Event) -> None:
        """Update the cursor-position tag box as the mouse moves over the text."""
        if self.token_map is None:
            return
        tk_index = self.text_widget.index(f"@{event.x},{event.y}")
        tk_line_i, tk_char_i = [int(x) for x in tk_index.split('.')]
        slate_line = tk_line_i - 1
        adj_char = self._strip_pipe_offset(tk_line_i, tk_char_i)
        token = self.token_map.char_to_token(slate_line, adj_char)

        # Update annotator info panel (regardless of selection state)
        if self._adjudication_mode:
            self._update_annotator_info(slate_line, token)

        if self.current_span is not None:
            return  # Selection is active; box is managed by _restore_selection
        if token is None:
            self._update_cursor_tags([])
            return
        names = []
        for ann in self.annotation_set.annotations:
            if ann.overlaps_span(slate_line, token, token):
                for internal in sorted(ann.labels):
                    names.append(self._label_display_name(internal))
        self._update_cursor_tags(names)

    def _label_display_name(self, internal: str) -> str:
        """Display name for an internal label, e.g. 'label:F-UP' → 'F-UP'."""
        lc = self.config.internal_to_config.get(internal)
        if lc:
            return lc.name
        return internal[len('label:'):] if internal.startswith('label:') else internal

    def _on_mouse_leave(self, _event: tk.Event) -> None:
        """Clear hover-dependent displays when the mouse leaves the text."""
        self._update_cursor_tags([])
        if self._adjudication_mode:
            self._update_annotator_info(None, None)

    def _update_annotator_info(
        self, slate_line: Optional[int], token: Optional[int],
    ) -> None:
        """Show/hide the annotator info overlay in the bottom-right of the text area."""
        if not hasattr(self, '_ann_info_label'):
            return
        if slate_line is None or token is None:
            self._ann_info_frame.place_forget()
            self._ann_info_visible = False
            return
        info = {
            name: self._shown(labels)   # only the groups on screen
            for name, labels in self._token_annotator_info.get((slate_line, token), {}).items()
        }
        if not any(info.values()):
            self._ann_info_frame.place_forget()
            self._ann_info_visible = False
            return
        lines = []
        for name in self._annotator_names:
            if name in self._empty_annotators:
                continue   # left out of this document's comparison
            labels = info.get(name, set())
            if labels:
                label_names = [self._label_display_name(i) for i in sorted(labels)]
                lines.append(f"{name}:  {', '.join(label_names)}")
            else:
                lines.append(f"{name}:  \u2014")
        self._ann_info_label.config(text='\n'.join(lines))
        self._ann_info_visible = True
        self._reposition_ann_info()

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

        # If sel.last is at char 0 of a line (e.g. a triple-click selects a
        # line plus its newline), the selection actually ends at the end of
        # the previous line.  Use that line's widget end so the pipe
        # adjustment below is applied to the right line.
        if end_tk_char == 0 and end_tk_line > 1:
            end_tk_line -= 1
            end_tk_char = int(
                self.text_widget.index(f"{end_tk_line}.end").split('.')[1]
            )

        start_sl = start_tk_line - 1   # slate 0-indexed line
        end_sl   = end_tk_line   - 1

        # Subtract any pipe-delimiter characters inserted before each position
        # so that the offsets match the original text that TokenMap knows about.
        start_tk_char = self._strip_pipe_offset(start_tk_line, start_tk_char)
        end_tk_char   = self._strip_pipe_offset(end_tk_line,   end_tk_char)
        last_char     = end_tk_char - 1   # sel.last is exclusive

        # --- Determine drag direction: press point vs release point -------
        # (Comparing the press point with sel.last can't work: the press
        # point is never after sel.last, whichever way the mouse moved.)
        ltr = True  # default: left-to-right
        if self._drag_anchor and self._drag_release:
            try:
                ltr = self.text_widget.compare(self._drag_anchor, '<=', self._drag_release)
            except tk.TclError:
                pass

        # --- Resolve tokens -----------------------------------------------
        # L→R: floor-snap the end (don't overshoot right into the next token).
        # R→L: ceiling-snap the start (don't overshoot left into the prev token).
        # In either direction, a start past the last token of its line (or an
        # end before the first token of its line) selects nothing on that
        # line, so it resolves to None and moves to the adjacent line below.
        start_snap, end_snap = ('nearest', 'floor') if ltr else ('ceiling', 'nearest')
        if self.token_map.is_after_last_token(start_sl, start_tk_char):
            start_tok = None
        else:
            start_tok = self.token_map.char_to_token(start_sl, start_tk_char, snap=start_snap)
        if last_char < 0 or self.token_map.is_before_first_token(end_sl, last_char):
            end_tok = None
        else:
            end_tok = self.token_map.char_to_token(end_sl, last_char, snap=end_snap)

        # No token at/after the start on its line: begin at the next line that has one
        if start_tok is None:
            for ln in range(start_sl + 1, self.token_map.num_lines()):
                if self.token_map.num_tokens(ln) > 0:
                    start_sl, start_tok = ln, 0
                    break

        # No token at/before the end on its line: finish at the previous line that has one
        if end_tok is None:
            for ln in range(end_sl - 1, -1, -1):
                if self.token_map.num_tokens(ln) > 0:
                    end_sl, end_tok = ln, self.token_map.num_tokens(ln) - 1
                    break

        # Nothing to select (only whitespace or blank lines were selected)
        if (start_tok is None or end_tok is None
                or (end_sl, end_tok) < (start_sl, start_tok)):
            self._clear_selection()
            self.status_var.set("No words in selection")
            return

        self.current_span = (start_sl, start_tok, end_sl, end_tok)

        # --- Update visual selection to full token boundaries -------------
        rng = self._span_widget_range(start_sl, start_tok, end_sl, end_tok)
        if rng:
            self.text_widget.tag_remove('sel', '1.0', 'end')
            self.text_widget.tag_add('sel', *rng)

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
        if not self._is_shown(lc.internal):
            self.status_var.set(
                f"'{lc.name}' is in the {lc.group} layer, which is hidden. "
                f"Press Tab to switch to it."
            )
            return
        if self.current_span is None:
            self.status_var.set(
                f"Select some text first, then press [{lc.key}] to apply '{lc.name}'"
            )
            return

        start_sl, start_tok, end_sl, end_tok = self.current_span

        # Save undo snapshot before mutating
        self.undo_stack.append(self.annotation_set.copy())

        # Mutual-exclusion: if this label belongs to a group, remove any
        # other labels from the same group on the tokens covered by the span
        # (an annotation extending beyond the span keeps them elsewhere).
        if lc.group and lc.group in self.config.groups:
            rivals = self.config.groups[lc.group] - {lc.internal}
            if rivals:
                self.annotation_set.remove_labels_in_range(
                    rivals, start_sl, start_tok, end_sl, end_tok, self.token_map,
                )

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
        """Remove every annotation that overlaps the current selection.

        With layers, only the active layer's labels are removed: the other
        layers aren't on screen, and always-shown labels usually run across
        the active layer's spans.
        """
        if self.current_span is None:
            self.status_var.set("Select text first, then press 'u' to remove annotations")
            return

        start_sl, start_tok, end_sl, end_tok = self.current_span
        if self._active_layer is not None:
            layer_labels = self.config.groups[self._active_layer]
            snapshot = self.annotation_set.copy()
            removed = self.annotation_set.remove_labels_overlapping_range(
                layer_labels, start_sl, start_tok, end_sl, end_tok,
            )
            if not removed:
                self.status_var.set(
                    f"No {self._active_layer} labels on the selection to remove"
                )
                return
            self.undo_stack.append(snapshot)
            message = f"Removed {self._active_layer} labels on selected span"
        else:
            self.undo_stack.append(self.annotation_set.copy())
            self.annotation_set.remove_overlapping_range(
                start_sl, start_tok, end_sl, end_tok
            )
            message = "Removed all annotations on selected span"

        self._redraw_annotations()
        self.has_unsaved = True
        self._clear_selection()
        self.status_var.set(message)

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
        rng = self._span_widget_range(*self.current_span)
        if rng:
            self.text_widget.tag_remove('sel', '1.0', 'end')
            self.text_widget.tag_add('sel', *rng)
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
                        names.append(self._label_display_name(internal))
        return names

    # ------------------------------------------------------------------
    # Save / navigate
    # ------------------------------------------------------------------

    def _working_annotations(self) -> AnnotationSet:
        """The annotations being edited for the current file.

        While an annotator's work is being viewed (adjudication mode),
        self.annotation_set temporarily holds *their* annotations; the
        adjudicator's own are parked in self._saved_annotation_set.
        """
        if self._viewing_annotator is not None and self._saved_annotation_set is not None:
            return self._saved_annotation_set
        return self.annotation_set

    def _try_save(self) -> Optional[OSError]:
        """Save the current file's annotations; return the error, or None."""
        if self.token_map is None:
            return None   # no file loaded, so nothing to save
        ann_path = self._annotation_path(self.files[self.current_idx])
        try:
            self._working_annotations().save(ann_path)
        except OSError as exc:
            return exc
        self.has_unsaved = False
        self.status_var.set(f"Saved → {os.path.basename(ann_path)}")
        return None

    def _save_current(self) -> None:
        err = self._try_save()
        if err is not None:
            messagebox.showerror("Save Error", f"Could not save:\n{err}")

    def _confirm_discard(self, err: OSError, action: str) -> bool:
        """After a failed save, ask whether to *action* anyway (losing changes)."""
        return messagebox.askyesno(
            "Save Error",
            f"Could not save:\n{err}\n\n{action} anyway and discard your changes?",
            icon='warning', default='no',
        )

    def _save_before_leaving(self, action: str) -> bool:
        """Save before leaving the current file; return True if OK to leave."""
        err = self._try_save()
        if err is None or not self.has_unsaved:
            return True
        return self._confirm_discard(err, action)

    def _go_next(self) -> None:
        if self.current_idx >= len(self.files) - 1:
            self.status_var.set("Already at the last file")
            return
        if self._save_before_leaving("Go to the next file"):
            self._load_first_available(range(self.current_idx + 1, len(self.files)))

    def _go_prev(self) -> None:
        if self.current_idx <= 0:
            self.status_var.set("Already at the first file")
            return
        if self._save_before_leaving("Go to the previous file"):
            self._load_first_available(range(self.current_idx - 1, -1, -1))

    def _show_help(self) -> None:
        """Open a modal help window with keyboard shortcut reference."""
        win = tk.Toplevel(self.root)
        win.title("Help — Keyboard Shortcuts")
        win.configure(bg='#2c3e50')

        label_lines = '\n'.join(
            f"  [{lc.key}]            Apply / toggle label '{lc.name}'"
            + (f" ({lc.group} layer)" if lc.group in self.config.layers else '')
            for lc in self.config.labels.values()
        )
        if self._active_layer is not None:
            remove_line = "  u                    Remove the current layer's labels on selection\n"
            layer_section = (
                "Layers\n"
                "  Tab                  Show the next layer\n"
                "  Shift+Tab            Show the previous layer\n"
                f"  ({' / '.join(self.config.layers)}; only the layer shown\n"
                "  can be edited, other groups are always shown)\n\n"
            )
        else:
            remove_line = "  u                    Remove all annotations on selection\n"
            layer_section = ''

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
            f"{remove_line}"
            "  Ctrl+Z               Undo last action\n"
            "  Escape               Clear current selection\n\n"
            f"{layer_section}"
            "Usage\n"
            "  1. Click and drag to select text.\n"
            "  2. Press a label key to annotate the selection.\n"
            "  3. Re-selecting the same span and pressing the same\n"
            "     label key toggles (removes) that label.\n"
            "  4. Annotations are saved automatically when\n"
            "     navigating between files.\n"
        )

        # Tall enough for the whole text (it grows with the number of
        # labels), but no taller than the screen
        help_font = tkfont.Font(family='Courier', size=11)
        height = help_text.count('\n') * help_font.metrics('linespace') + 110
        height = min(height, win.winfo_screenheight() - 120)
        win.geometry(f"600x{max(height, 420)}")
        win.resizable(False, True)

        txt = tk.Text(
            win, wrap='word', bg='#2c3e50', fg='white',
            font=help_font, padx=16, pady=12,
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
        # Update annotator info overlay font to match
        if hasattr(self, '_ann_info_label'):
            self._ann_info_label.config(font=('Helvetica', self.font_size))
            self._reposition_ann_info()
        # Reconfigure style-based tags with the new size
        self._configure_tags()
        # Drop the combo tags (and their ranges) so they are rebuilt at the new size
        for combo_tag in self._combo_tags.values():
            self.text_widget.tag_delete(combo_tag)
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
                err = self._try_save()
                if err is not None and not self._confirm_discard(err, "Quit"):
                    return
        self.root.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_app(
    config: Config,
    files: List[str],
    output_dir: Optional[str],
    annotator: str,
    adjudication_annotators: Optional[List[tuple]] = None,
) -> None:
    root = tk.Tk()
    _app = AnnotationApp(
        root, config, files, output_dir, annotator,
        adjudication_annotators=adjudication_annotators,
    )
    root.mainloop()
