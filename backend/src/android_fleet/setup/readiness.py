"""Fail-closed recognition of the actual focused Termux window."""

import re


def termux_has_focus(output: str) -> bool | None:
    """None means the dump lacks focus data; window/activity listings prove nothing."""
    focused = [line for line in output.splitlines() if re.match(r"^\s*mCurrentFocus=", line)]
    if not focused:
        return None
    return all(
        re.search(
            r"mCurrentFocus=Window\{[^}]*\bu0\s+"
            r"com\.termux/(?:com\.termux)?\.app\.TermuxActivity[ }$]",
            line,
        )
        is not None
        for line in focused
    )
