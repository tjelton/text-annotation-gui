"""
config.py — Parse the label configuration file.

Config file format (lines starting with # are comments):
    Label:  <name>  <key>  <colour>

Example:
    Label:  F-UP    f   red
    Label:  F-BK    b   #3498db
"""

import re
from dataclasses import dataclass
from typing import Dict


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


@dataclass
class LabelConfig:
    name: str      # Display name, e.g. "F-UP"
    internal: str  # Slate-compatible name with prefix, e.g. "label:F-UP"
    key: str       # Single keyboard character, e.g. "f"
    colour: str    # Hex colour string, e.g. "#e74c3c"
    tag: str       # tkinter tag name (safe for use as tag identifier)


class Config:
    def __init__(self) -> None:
        # key char → LabelConfig
        self.labels: Dict[str, LabelConfig] = {}
        # internal name (e.g. "label:F-UP") → LabelConfig
        self.internal_to_config: Dict[str, LabelConfig] = {}

    @classmethod
    def from_file(cls, filepath: str) -> 'Config':
        config = cls()
        with open(filepath, 'r', encoding='utf-8') as f:
            for lineno, raw in enumerate(f, 1):
                line = raw.strip()
                if not line or line.startswith('#'):
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

                # Resolve colour to hex
                hex_colour = _resolve_colour(colour, lineno)

                internal = f"label:{name}"
                # Tag name must be safe for tkinter (no : - special chars)
                tag = 'lbl_' + re.sub(r'[^A-Za-z0-9_]', '_', name)

                lc = LabelConfig(
                    name=name, internal=internal,
                    key=key, colour=hex_colour, tag=tag,
                )
                config.labels[key] = lc
                config.internal_to_config[internal] = lc

        if not config.labels:
            raise ValueError("Config file defines no labels")
        return config


def _resolve_colour(colour: str, lineno: int) -> str:
    if colour in COLOUR_MAP:
        return COLOUR_MAP[colour]
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
