"""
config.py — Parse the label configuration file.

Config file format (lines starting with # are comments):
    Label:  <name>  <key>  <colour_or_style>  [group="<group>"]

The fourth field can be:
  - A colour: named (e.g. red, blue) or hex (#RRGGBB / #RGB)
  - A text style: bold, italic, or underline

An optional fifth field, group="<group>", makes labels in the same group
mutually exclusive: applying one automatically removes any other label
from the same group on the affected tokens.  A trailing # comment is
allowed; any other extra text is an error.

An optional line names groups that take turns on screen:
    Layers:  <group>  <group>  [...]

Only one of these "layers" is shown and editable at a time (Tab switches);
groups not named, and labels with no group, are always shown.  Without a
Layers: line every label is shown at once.

Example:
    Label:  F-UP    f   red
    Label:  F-BK    b   #3498db
    Label:  PER     p   italic
    Label:  DATE    d   bold
    Label:  SELF    q   #e67e22  group="regulation"
    Label:  TASK    w   #9b59b6  group="regulation"
"""

import re
import shlex
from dataclasses import dataclass
from typing import Dict, List, Optional


# Keys reserved for navigation / built-in commands
RESERVED_KEYS = {'[', ']', 'u'}

# Named colour aliases → hex
COLOUR_MAP: Dict[str, str] = {
    'red':     '#e74c3c',
    'blue':    '#3498db',
    'green':   '#2ecc71',
    'yellow':  '#f1c40f',
    'magenta': '#9b59b6',
    'purple':  '#8e44ad',
    'cyan':    '#1abc9c',
    'orange':  '#e67e22',
    'pink':    '#e91e8c',
    'brown':   '#795548',
    'white':   '#ffffff',
    'black':   '#000000',
    'lime':    '#cddc39',
    'indigo':  '#3f51b5',
    'teal':    '#009688',
    'coral':   '#ff7043',
    'navy':    '#1a237e',
}

# Text-style keywords (used instead of colour)
STYLE_SET = {'bold', 'italic', 'underline'}


@dataclass
class LabelConfig:
    name: str                # Display name, e.g. "F-UP"
    internal: str            # Slate-compatible name with prefix, e.g. "label:F-UP"
    key: str                 # Single keyboard character, e.g. "f"
    colour: Optional[str]    # Hex colour string, e.g. "#e74c3c" (None for style-based)
    style: Optional[str]     # "bold", "italic", or "underline" (None for colour-based)
    tag: str                 # tkinter tag name (safe for use as tag identifier)
    group: Optional[str] = None  # Mutual-exclusion group name, e.g. "regulation"


class Config:
    def __init__(self) -> None:
        # key char → LabelConfig
        self.labels: Dict[str, LabelConfig] = {}
        # internal name (e.g. "label:F-UP") → LabelConfig
        self.internal_to_config: Dict[str, LabelConfig] = {}
        # group name → set of internal label names in that group
        self.groups: Dict[str, set] = {}
        # Groups that take turns on screen, in Tab order (empty: show all)
        self.layers: List[str] = []
        # Problems that don't stop the tool, printed at startup
        self.warnings: List[str] = []

    @classmethod
    def from_file(cls, filepath: str) -> 'Config':
        config = cls()
        name_lines: Dict[str, int] = {}   # label name → line it was defined on
        layer_names: List[str] = []
        layers_line: Optional[int] = None
        # utf-8-sig: ignore the byte-order mark some Windows editors add, which
        # would otherwise hide the first line from the 'Label:' check below.
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            for lineno, raw in enumerate(f, 1):
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith('Layers:'):
                    if layers_line is not None:
                        raise ValueError(
                            f"Config line {lineno}: 'Layers:' is already "
                            f"given on line {layers_line}"
                        )
                    layers_line = lineno
                    try:
                        # shlex: allows "quoted names" and a trailing # comment
                        layer_names = shlex.split(
                            line[len('Layers:'):], comments=True,
                        )
                    except ValueError as exc:   # e.g. an unclosed quote
                        raise ValueError(f"Config line {lineno}: {exc}") from None
                    continue
                if not line.startswith('Label:'):
                    continue  # silently skip unknown directives

                parts = line.split()
                if len(parts) < 4:
                    raise ValueError(
                        f"Config line {lineno}: 'Label:' needs 3 fields "
                        f"(name key colour), got: {line!r}"
                    )
                _, name, key, colour = parts[0], parts[1], parts[2], parts[3]

                # Validate key
                if len(key) != 1:
                    raise ValueError(
                        f"Config line {lineno}: key must be a single character, got {key!r}"
                    )
                if key in RESERVED_KEYS:
                    raise ValueError(
                        f"Config line {lineno}: key {key!r} is reserved "
                        f"({', '.join(sorted(RESERVED_KEYS))})"
                    )
                if key in config.labels:
                    raise ValueError(
                        f"Config line {lineno}: key {key!r} already used by "
                        f"label '{config.labels[key].name}'"
                    )
                if name in name_lines:
                    raise ValueError(
                        f"Config line {lineno}: label name {name!r} is already "
                        f"defined on line {name_lines[name]}"
                    )
                name_lines[name] = lineno

                # Resolve appearance: text style or colour
                if colour.lower() in STYLE_SET:
                    hex_colour = None
                    style = colour.lower()
                else:
                    hex_colour = _resolve_colour(colour, lineno)
                    style = None

                # Optional group="..." field, then optionally a # comment.
                # Anything else is an error: a typo such as group=level
                # (no quotes) must not silently disable mutual exclusion.
                rest = line.split(None, 4)[4] if len(parts) > 4 else ''
                group = None
                group_match = re.match(r'group="([^"]+)"\s*', rest)
                if group_match:
                    group = group_match.group(1)
                    rest = rest[group_match.end():]
                if rest and not rest.startswith('#'):
                    raise ValueError(
                        f"Config line {lineno}: unrecognised text {rest!r} after "
                        f"the colour; the only optional field is group=\"<name>\""
                    )

                internal = f"label:{name}"
                # Tag name must be safe for tkinter (no : - special chars).
                # The index keeps it unique: "F-UP" and "F_UP" would
                # otherwise both become "lbl_F_UP" and share one style.
                safe = re.sub(r'[^A-Za-z0-9_]', '_', name)
                tag = f'lbl_{len(config.labels)}_{safe}'

                lc = LabelConfig(
                    name=name, internal=internal,
                    key=key, colour=hex_colour, style=style, tag=tag,
                    group=group,
                )
                config.labels[key] = lc
                config.internal_to_config[internal] = lc
                if group:
                    config.groups.setdefault(group, set()).add(internal)

        if not config.labels:
            raise ValueError("Config file defines no labels")
        if layers_line is not None:
            config.layers = _check_layers(layer_names, config.groups, layers_line)
            config.warnings.extend(_layer_clash_warnings(config))
        return config


def _check_layers(names: List[str], groups: Dict[str, set], lineno: int) -> List[str]:
    """Validate the group names on a 'Layers:' line and return them."""
    if len(names) < 2:
        raise ValueError(
            f"Config line {lineno}: 'Layers:' needs at least two groups "
            f"to switch between"
        )
    for i, name in enumerate(names):
        if name in names[:i]:
            raise ValueError(
                f"Config line {lineno}: group {name!r} is listed twice in 'Layers:'"
            )
        if name not in groups:
            known = ', '.join(sorted(groups)) or 'none'
            raise ValueError(
                f"Config line {lineno}: 'Layers:' names group {name!r}, but no "
                f"label has group=\"{name}\" (groups in this file: {known})"
            )
    return list(names)


def _layer_clash_warnings(config: 'Config') -> List[str]:
    """Warn where a layer and an always-shown label would be drawn alike.

    Layers never appear together, so they can share colours and styles,
    but each one is drawn on top of the always-shown labels: two highlight
    colours on one token turn grey, and a shared text style can't be told
    apart.
    """
    always = [lc for lc in config.labels.values() if lc.group not in config.layers]
    if not always:
        return []
    always_names = ', '.join(lc.name for lc in always)
    always_colour = any(lc.colour for lc in always)
    always_styles = {lc.style for lc in always if lc.style}
    warnings = []
    for layer in config.layers:
        members = [lc for lc in config.labels.values() if lc.group == layer]
        if always_colour and any(lc.colour for lc in members):
            warnings.append(
                f"layer {layer!r} and the always-shown labels ({always_names}) "
                f"both use highlight colours, so text where they overlap turns "
                f"grey. Give one of them text styles (bold, italic, underline)."
            )
        shared = always_styles & {lc.style for lc in members if lc.style}
        if shared:
            warnings.append(
                f"layer {layer!r} and the always-shown labels ({always_names}) "
                f"both use {', '.join(sorted(shared))}, so they can't be told "
                f"apart where they overlap."
            )
    return warnings


def _resolve_colour(colour: str, lineno: int) -> str:
    if colour.lower() in COLOUR_MAP:
        return COLOUR_MAP[colour.lower()]
    # Accept #RGB or #RRGGBB
    if re.match(r'^#[0-9A-Fa-f]{3}$', colour):
        r, g, b = colour[1], colour[2], colour[3]
        return f"#{r}{r}{g}{g}{b}{b}"
    if re.match(r'^#[0-9A-Fa-f]{6}$', colour):
        return colour
    raise ValueError(
        f"Config line {lineno}: unknown colour {colour!r}. "
        f"Use a name ({', '.join(sorted(COLOUR_MAP))}) or a hex colour (#RRGGBB)."
    )
