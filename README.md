# Annotation Tool

A lightweight, keyboard-driven GUI for span-level text annotation. Select text with the mouse, apply labels with single keystrokes, and navigate through a folder of documents. Output files are fully compatible with [slate](https://github.com/jkkummerfeld/slate).

---

## Contents

- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [The Interface](#the-interface)
- [Step-by-Step Annotation Workflow](#step-by-step-annotation-workflow)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Configuration File](#configuration-file)
- [Command-Line Reference](#command-line-reference)
- [Output File Format](#output-file-format)
- [Multi-Annotator Workflows](#multi-annotator-workflows)
- [Tips and Common Questions](#tips-and-common-questions)
- [Acknowledgements](#acknowledgements)

---

## Requirements

- Python 3.8 or later
- No third-party packages — the tool uses only Python's standard library (`tkinter`, which ships with Python on macOS, Windows, and most Linux distributions)

**Checking your Python version:**

```bash
python3 --version
```

**Checking tkinter is available:**

```bash
python3 -c "import tkinter; print('tkinter OK')"
```

> **Linux note:** If tkinter is missing, install it with `sudo apt install python3-tk` (Debian/Ubuntu) or the equivalent for your distribution.

---

## Quick Start

```bash
# 1. Clone or download this repository
git clone <repo-url>
cd annotation-tool

# 2. Launch the tool with a folder of .txt files and a config file
python3 -m annotation_tool -f ./texts -c config_example.txt
```

This opens the annotation window. Select text, press a label key, and your annotation is saved automatically when you move to the next file.

---

## The Interface

```
┌──────────────────────────────────────────────────────────────────┐
│  [◀ Previous]   annotator — 01.txt   (1 / 50)   [Save] [Help] [Next ▶]  │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Marie Curie was born in Warsaw in 1867 and later               │
│  moved to Paris, where she conducted research at                 │
│  the University of Paris.                                        │
│                                            ↑ scrollable          │
├──────────────────────────────────────────────────────────────────┤
│  Labels:  [p] PER ████  [o] ORG ████  [l] LOC ████  …           │
├──────────────────────────────────────────────────────────────────┤
│  Status: Ready                                                    │
└──────────────────────────────────────────────────────────────────┘
```

| Area | Purpose |
|---|---|
| **Header** | Current filename, annotator name, progress counter, navigation and action buttons |
| **Text area** | The document being annotated; scrollable, read-only |
| **Legend** | Colour swatches for every label, with the keyboard key shown in brackets |
| **Status bar** | Feedback on the last action (selection info, save confirmation, errors) |

---

## Step-by-Step Annotation Workflow

### 1. Select text

Click and drag with the mouse over the words you want to label. The selection automatically **snaps to token boundaries** — partial words are expanded to include the full token on either side.

### 2. Apply a label

With text selected, press the **single-character key** for the label you want (shown in the legend, e.g. `p` for PER). The selected span is immediately highlighted in the label's colour.

- If the exact same span already carries that label, pressing the key again **removes** it (toggle behaviour).
- A span can hold **multiple labels**. If two or more labels cover the same token, it is shown in a grey "multi-label" colour with underlining.

### 3. Remove annotations

Select the span you want to clear and press **`u`**. This removes every annotation overlapping that selection, regardless of label.

### 4. Undo

Press **Ctrl+Z** to undo the most recent annotation action. You can undo repeatedly to step back through your changes.

### 5. Navigate between files

Press **`]`** (or the **Next** button) to move to the next file. The current file is **saved automatically** before loading the next one.

Press **`[`** (or the **Previous** button) to go back.

### 6. Save manually

Press **Ctrl+S** (or the **Save** button) at any time. You do not need to save before navigating — auto-save handles this — but manual save is available if you prefer.

### 7. Quit

Close the window or press **Ctrl+Q**. If there are unsaved changes you will be asked whether to save before quitting.

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| *Label key* (e.g. `p`, `o`, `l`) | Apply or toggle that label on the selected text |
| `u` | Remove **all** annotations overlapping the current selection |
| `]` | Next file (auto-saves first) |
| `[` | Previous file (auto-saves first) |
| `Ctrl+S` | Save current file |
| `Ctrl+Z` | Undo last annotation action |
| `Ctrl+Q` | Quit (prompts to save if unsaved changes exist) |
| `Escape` | Clear the current selection |
| `↑` `↓` `Page Up` `Page Down` | Scroll the text area |

> Label keys are defined in your configuration file. They cannot conflict with the reserved keys listed above (`[`, `]`, `u`).

The **Help** button in the header opens a reference window with these shortcuts, including your specific label keys.

---

## Configuration File

The configuration file tells the tool what labels to use, which key activates each label, and what colour to display.

### Format

```
# Lines starting with # are comments and are ignored
# Blank lines are also ignored
# Format: Label:  <name>  <key>  <colour>

Label:  PER     p   #e74c3c
Label:  ORG     o   #3498db
Label:  LOC     l   #2ecc71
Label:  DATE    d   #e67e22
Label:  MISC    m   #9b59b6
```

Each `Label:` line has three fields (whitespace-separated):

| Field | Description | Example |
|---|---|---|
| `name` | The label identifier. Appears in annotation files as `label:<name>`. | `PER` |
| `key` | A **single character** key the annotator presses to apply the label. | `p` |
| `colour` | A colour name or hex code for the highlight colour. | `red` or `#e74c3c` |

### Supported colour names

`red`, `blue`, `green`, `yellow`, `magenta`, `purple`, `cyan`, `orange`, `pink`, `brown`, `white`, `black`, `lime`, `indigo`, `teal`, `coral`, `navy`

Any standard hex colour (`#RRGGBB` or `#RGB`) is also accepted.

### Rules

- Each key must be unique across all labels.
- The keys `[`, `]`, and `u` are **reserved** for navigation and cannot be used as label keys.
- Label names must be unique.
- At least one label must be defined.

A ready-to-use example file is provided at `config_example.txt`.

---

## Command-Line Reference

```
python3 -m annotation_tool -f <folder> -c <config> [options]
```

### Required arguments

| Argument | Description |
|---|---|
| `-f`, `--folder` | Path to the folder containing `.txt` files to annotate |
| `-c`, `--config` | Path to the label configuration file |

### Optional arguments

| Argument | Description |
|---|---|
| `-o`, `--output DIR` | Directory where `.annotations` files are written. Defaults to the same folder as the input files. |
| `-a`, `--annotator NAME` | Annotator identifier. Shown in the header bar and used in output filenames so multiple annotators can work on the same files independently (see [Multi-Annotator Workflows](#multi-annotator-workflows)). |
| `--resume` | Load any existing `.annotations` files and continue editing them, rather than starting fresh. |

### Examples

```bash
# Minimal — annotate a folder, save annotations alongside the source files
python3 -m annotation_tool -f ./texts -c config_example.txt

# Separate output directory
python3 -m annotation_tool -f ./texts -c config.txt -o ./annotations

# Named annotator with a dedicated output folder
python3 -m annotation_tool -f ./texts -c config.txt -o ./annotations -a alice

# Resume a previous session (re-loads existing annotations)
python3 -m annotation_tool -f ./texts -c config.txt -o ./annotations -a alice --resume
```

---

## Output File Format

Annotation files are written in [slate](https://github.com/jkkummerfeld/slate)-compatible format, so they can be read by slate and other tools that use the same convention.

### File naming

| Scenario | Output filename |
|---|---|
| No annotator name | `<input_file>.annotations` (e.g. `01.txt.annotations`) |
| With `--annotator alice` | `<input_file>.alice.annotations` (e.g. `01.txt.alice.annotations`) |

By default, output files are placed in the same directory as the input files. Use `-o` to redirect them.

### File contents

Each line in the annotation file describes one annotated span. Using NER as an example:

```
# Single token (line 0, token 0) labelled as a person:
(0, 0) - label:PER

# Token span on a single line (line 0, tokens 0–1, e.g. "Marie Curie"):
((0, 0), (0, 1)) - label:PER

# Span with multiple labels:
((0, 0), (0, 1)) - label:ORG label:PER

# Single token with a location label (line 1, token 3):
(1, 3) - label:LOC
```

**Coordinate system:**

- Lines and tokens are **0-indexed**.
- Tokenisation matches slate exactly: each line is split on whitespace after stripping leading/trailing spaces. Empty lines count as a line number but contain no tokens.
- A multi-line selection is stored as one annotation per line (slate does not support cross-line spans).

**Label prefix:** All label names in the output are prefixed with `label:` (e.g. `label:PER`), matching slate's internal convention.

---

## Multi-Annotator Workflows

To have multiple people annotate the same files independently, give each annotator their own name with `-a` and a shared output directory with `-o`.

```bash
# Annotator 1
python3 -m annotation_tool -f ./texts -c config.txt -o ./annotations -a alice

# Annotator 2 (on their own machine)
python3 -m annotation_tool -f ./texts -c config.txt -o ./annotations -a bob
```

This produces separate files for each person:

```
annotations/
  01.txt.alice.annotations
  01.txt.bob.annotations
  02.txt.alice.annotations
  02.txt.bob.annotations
  ...
```

These can then be compared or adjudicated using slate's built-in tools (inter-annotator agreement, adjudication mode), since the file format is identical.

---

## Tips and Common Questions

**Files are loaded in natural sort order** (`1.txt`, `2.txt`, … `10.txt`, not `1.txt`, `10.txt`, `2.txt`), so numbering your input files works as expected.

**Annotations are auto-saved when navigating.** You will not lose work by clicking Next or Previous. Manual save (`Ctrl+S`) is available if you want to save mid-file.

**Toggling removes a label.** If you select the exact same span and press the same label key again, the label is removed. This is intentional — it lets you correct mistakes without using undo.

**Undo only affects the current file.** The undo stack is reset when you load a new file.

**You can apply multiple labels to the same span.** Press different label keys on the same selection. Spans with more than one label are shown in grey with underlining; the legend identifies these as "multi" overlaps.

**Resuming a session.** If you close the tool and want to continue later, re-run the same command with `--resume`. Without `--resume`, any existing `.annotations` files are still loaded and displayed — `--resume` simply makes this explicit and is useful as a reminder in scripts.

**The text cannot be edited.** The tool is read-only with respect to the source documents. Only annotations are written to disk.

**Colour accessibility.** If any label colours are hard to distinguish, you can change them in the config file — any hex colour is accepted. A restart is required for config changes to take effect.

---

## Acknowledgements

This tool is a standalone GUI for span annotation that produces output compatible with [**slate**](https://github.com/jkkummerfeld/slate), a terminal-based annotation tool developed by Dr. Jonathan Kummerfeld. The file format is intentionally identical to slate's so that annotations can be exchanged between the two tools and slate's inter-annotator agreement and adjudication features can be used downstream.

> Kummerfeld, J. K. (2019). [slate: A Super-Lightweight Annotation Tool for Experts](https://aclanthology.org/P19-3003/). In *Proceedings of the 57th Annual Meeting of the Association for Computational Linguistics: System Demonstrations* (pp. 15–21). Association for Computational Linguistics.
