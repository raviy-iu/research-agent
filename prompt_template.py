"""
prompt_template.py – Prompt template system for structured research queries.

Templates live in prompts.json and can be edited to improve search quality
over time. Each template has:
  - A {placeholder} string with required and optional keys
  - A version number to track revisions
  - Notes on what works best

CLI usage (via main.py):
    uv run main.py --template fmea --set industry=cement --set equipment=kiln
    uv run main.py --list-templates

Module API:
    from prompt_template import load_templates, render, list_templates
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

PROMPTS_FILE = Path(__file__).parent / "prompts.json"

console = Console()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PromptTemplate:
    name: str
    description: str
    template: str
    required_keys: list[str]
    optional_keys: dict[str, str]   # key -> default value
    version: int = 1
    notes: str = ""

    @property
    def all_keys(self) -> list[str]:
        return self.required_keys + list(self.optional_keys.keys())

    def render(self, values: dict[str, str]) -> str:
        """
        Render the template with provided values, filling optional keys
        with their defaults when not supplied.

        Parameters
        ----------
        values : dict[str, str]
            Key-value pairs from --set KEY=VALUE CLI arguments.

        Returns
        -------
        str
            The rendered query string.

        Raises
        ------
        KeyError
            If a required key is missing from *values*.
        """
        # Check all required keys are present
        missing = [k for k in self.required_keys if k not in values]
        if missing:
            raise KeyError(
                f"Template '{self.name}' requires: {missing}. "
                f"Provide them with --set KEY=VALUE"
            )

        # Build full context: defaults first, then user values override
        ctx: dict[str, str] = {**self.optional_keys, **values}

        # Render
        try:
            rendered = self.template.format_map(ctx)
        except KeyError as exc:
            raise KeyError(
                f"Template '{self.name}' has placeholder {exc} "
                f"that is not in required_keys or optional_keys. "
                f"Please fix prompts.json."
            ) from exc

        # Collapse extra whitespace
        return re.sub(r"\s{2,}", " ", rendered).strip()


# ---------------------------------------------------------------------------
# Load / registry
# ---------------------------------------------------------------------------

def load_templates(path: Path = PROMPTS_FILE) -> dict[str, PromptTemplate]:
    """Load all templates from the JSON file. Returns an ordered dict."""
    if not path.exists():
        console.print(
            f"[red]Error:[/red] Prompt templates file not found: {path}\n"
            "Create it or restore from the default."
        )
        sys.exit(1)

    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        console.print(f"[red]Error parsing {path}:[/red] {exc}")
        sys.exit(1)

    templates: dict[str, PromptTemplate] = {}
    for name, tpl in raw.get("templates", {}).items():
        templates[name] = PromptTemplate(
            name=name,
            description=tpl.get("description", ""),
            template=tpl.get("template", ""),
            required_keys=tpl.get("required_keys", []),
            optional_keys=tpl.get("optional_keys", {}),
            version=tpl.get("version", 1),
            notes=tpl.get("notes", ""),
        )
    return templates


# Module-level cache (loaded once per process)
_templates: dict[str, PromptTemplate] | None = None


def get_templates() -> dict[str, PromptTemplate]:
    global _templates
    if _templates is None:
        _templates = load_templates()
    return _templates


def get_template(name: str) -> PromptTemplate:
    """Return a template by name, or exit with a helpful error."""
    templates = get_templates()
    if name not in templates:
        available = ", ".join(sorted(templates.keys()))
        console.print(
            f"[red]Error:[/red] Template '{name}' not found.\n"
            f"Available templates: {available}\n"
            f"Use [bold]--list-templates[/bold] to see full details."
        )
        sys.exit(1)
    return templates[name]


def render(name: str, values: dict[str, str]) -> str:
    """Load template by name, render with values, and return the query string."""
    tpl = get_template(name)
    return tpl.render(values)


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def list_templates() -> None:
    """Print a formatted table of all available templates to the terminal."""
    templates = get_templates()

    table = Table(title="Available Prompt Templates", show_lines=True)
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Description", style="white")
    table.add_column("Required Keys", style="yellow")
    table.add_column("Optional Keys (defaults)", style="dim")
    table.add_column("v", justify="right", style="green")

    for name, tpl in templates.items():
        req = ", ".join(tpl.required_keys) if tpl.required_keys else "-"
        opt_parts = [f"{k}='{v}'" for k, v in tpl.optional_keys.items()]
        opt = "\n".join(opt_parts) if opt_parts else "-"
        table.add_row(name, tpl.description, req, opt, str(tpl.version))

    console.print(table)
    console.print(
        "\n[dim]Template file:[/dim] prompts.json  "
        "(edit to improve search quality over time)\n"
        "[dim]Usage:[/dim] uv run main.py --template <name> --set key=value\n"
        "[dim]Example:[/dim] uv run main.py --template fmea "
        "--set industry=cement --set equipment=kiln\n"
    )


def parse_set_args(set_args: list[str]) -> dict[str, str]:
    """
    Parse a list of 'KEY=VALUE' strings into a dict.

    Parameters
    ----------
    set_args : list[str]
        Values from repeated ``--set KEY=VALUE`` CLI arguments.

    Returns
    -------
    dict[str, str]

    Raises
    ------
    SystemExit
        If any entry is not in KEY=VALUE format.
    """
    result: dict[str, str] = {}
    for entry in set_args:
        if "=" not in entry:
            console.print(
                f"[red]Error:[/red] --set argument must be in KEY=VALUE format, "
                f"got: '{entry}'"
            )
            sys.exit(1)
        key, _, value = entry.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            console.print(
                f"[red]Error:[/red] Empty key in --set argument: '{entry}'"
            )
            sys.exit(1)
        result[key] = value
    return result


def show_template_preview(name: str, values: dict[str, str]) -> None:
    """Print the rendered template and its source before running the search."""
    tpl = get_template(name)
    rendered = tpl.render(values)

    console.print(
        f"[bold]Template:[/bold] [cyan]{name}[/cyan] "
        f"[dim](v{tpl.version})[/dim]"
    )
    console.print(f"[bold]Template string:[/bold] [dim]{tpl.template}[/dim]")
    if values:
        kv = "  ".join(f"{k}=[yellow]{v}[/yellow]" for k, v in values.items())
        console.print(f"[bold]Keys:[/bold] {kv}")
    console.print(f"[bold]Rendered query:[/bold] {rendered}")
    if tpl.notes:
        console.print(f"[dim]Notes: {tpl.notes}[/dim]")
    console.print()
