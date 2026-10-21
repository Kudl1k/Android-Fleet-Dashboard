# Android Fleet interface

The dashboard is an operational workspace for finding Android devices, assessing connection and telemetry state, and taking permitted actions. Keep the existing React, native HTML controls, Lucide icons, and CSS component classes. Preserve the authenticated ADB model and capability-driven controls.

## Direction

Refine the existing slate-and-blue interface. Give device identity, connection state, and observation freshness priority over decoration. Use one clear page heading and a specific primary action. Group fleet counts in one status strip rather than four unrelated cards. Use panels for distinct tasks, not every text group.

Desktop layout: navigation rail → page context and workspace controls → page heading and action → status and filters → devices or records. Below 760px, use a collapsible navigation disclosure, wrapping headings, stacked forms, and a two-column status strip. Keep long identities readable and horizontal table scrolling contained within its region.

## Tokens and components

`frontend/src/styles.css` owns both themes and shared component styles.

| Role | Dark | Light |
| --- | --- | --- |
| Background (`--bg`) | #0c111b | #f3f6fa |
| Panel (`--panel`) | #141d2b | #ffffff |
| Text (`--text`) | #edf3fb | #16243a |
| Secondary text (`--muted`) | #9aaac0 | #52647b |
| Accent (`--accent`) | #6daaff | #175dc2 |
| Control boundary (`--control-border`) | #56667e | #7c8ca3 |

Use `--on-accent` for primary-action text. Keep green for online/success, amber for degraded/warning, and red for errors, always with text. Subtle panel dividers use `--border`; interactive boundaries use the stronger control token.

Keep the incumbent Inter/system sans stack without adding font downloads. Body text is 14px; labels and supporting text are generally 12–13px; section headings 18px; page headings 29px (25px on phones). Phone inputs use 16px. Numeric comparisons use tabular figures; monospace is reserved for identifiers and code. Use the 4px spacing scale, 8px control radius, and 12px panel radius.

Reuse `.panel`, `.button`, `.primary`, `.badge`, `.toolbar`, `.actions`, `.grid`, and `.table-wrap`/`.table-scroll`. Buttons and inputs have a 44px minimum height. Use children and existing semantic markup for composition; do not add boolean-heavy component variants or a second component library.

## Interaction requirements

- Main navigation uses links and exposes the current route. Mobile navigation exposes expanded state, closes on selection, and returns focus to its toggle on Escape.
- Route changes reset scroll and move keyboard focus to main content. Browser titles identify the current page.
- Dialogs retain native modal behavior, have accessible names, and restore focus to their opener. Cancelling access discards the token draft.
- Tables that may scroll are named, focusable regions. Keep arrow-key scrolling and visible keyboard focus.
- Distinguish initial loading, no observations, no matching filters, empty registries, stale data, and request errors. Never turn missing telemetry into zero.
- Respect reduced motion; preserve immediate interaction feedback without decorative entrance animations.

See [UI review and validation](docs/UI_REVIEW.md) for findings and verification limits.

## Device workspace

The detail page reads in this order: identity and connection badge → telemetry freshness → key available observations → inspection and tools. Keep connection state separate from collection status. Display the successful collection timestamp once in the freshness area; last-seen belongs in identity diagnostics. Paused refresh describes the saved collection without claiming it is current. Failed status checks withhold current values while retaining history access.

Use one telemetry panel with up to four available observations, then native disclosures for performance, memory/storage, battery/thermal, and cumulative network counters. Missing metrics belong in one availability disclosure and mean “not observed,” not necessarily “unsupported.” Keep real zeros. Show an explicit empty state when there is no usable collection.

Identity/capabilities and historical charts are secondary disclosures. Load history on first opening and retain its range afterward. Group interactive tools below monitoring with clear summaries and workspace anchor links. Keep tool children mounted when collapsed; live stream status stays in its summary, terminal resizing remains owned by its ResizeObserver, and existing route/auth cleanup stays owned by each tool. Closing a disclosure does not stop a session. Use the tools' explicit Stop/Close actions.

On phones, key observations use two columns and metric groups become a single column. Long identities and labels wrap; toolbars wrap and table overflow stays inside the tool. Native summary controls retain visible focus and a 44px minimum target.

### Device actions and alignment

Use the explicit `.device-actions`, `.device-form-row`, and `.device-action-group` compositions for embedded tools; retain the existing generic `.actions` behavior on other pages. Routine device inspection and screen power have named groups. Restarts sit behind a divider, use the danger treatment, and retain confirmation. Application inspection/launch and force-stop/uninstall are separate groups within each package row. Session termination is separated from terminal editing/display tools.

Keep local actions beside their content: setup actions below instructions, connection settings in the connection heading, refresh beside application search, and record beside the program command. Desktop form buttons align to the input's bottom edge, not the label; inputs/selects and ordinary buttons are 44px high. On phones, form actions stack at full width while short action groups wrap naturally. Primary treatment marks the task's start/confirm action; secondary controls remain neutral. Changing pending labels reserve their width; expose busy state without shifting surrounding controls. Use 16px icons inside text buttons and the existing theme/state tokens.

### Device list rows and scrolling

Use `ListRegion` for naturally sized lists with a maximum height tied to the viewport. The region has an accessible name, keyboard focus, visible scrollbar styling and a continuation hint only when content actually overflows. Headings, loaded counts and filters remain outside. Keep the region mounted across polling updates; never reset its scroll position. Expanded content inside a list uses the outer region for scrolling, including nested observation tables, to avoid competing scroll containers.

Observation and identity data remain definition lists. Scalar readings have separate number/unit columns and tabular numerals; composite durations retain their complete formatting. State text and identities align left. Applications and historical observation data retain table markup, fixed column proportions and sticky column headings. Application rows stack into labelled blocks on phones while preserving their safe/destructive action groups. Operation and session records are lists with stable state/duration/action slots; long names and identifiers wrap. Only disclosure summaries and actions get hover feedback. Missing durations explicitly say “Unavailable”; no missing telemetry becomes zero.
