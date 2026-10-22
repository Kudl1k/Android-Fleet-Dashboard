# Android Fleet interface

The dashboard is an operational workspace for finding Android devices, assessing connection and telemetry state, and taking permitted actions. Preserve authenticated ADB, capability-driven controls, React, and Lucide icons. New and migrated device UI uses the source-owned shadcn/ui components in `frontend/src/components/ui` (Radix Nova). Other routes migrate incrementally; do not build another set of controls.

## Direction

Keep the slate-and-blue identity. Device identity, connection state, observation freshness and the next useful action outrank decoration. Use panels for distinct tasks, not individual readings. The fleet keeps its consolidated status strip.

Desktop layout: navigation rail → workspace controls → page heading and action → monitoring or task content. Below 760px, navigation becomes a disclosure, forms stack, actions wrap, and key observations use two columns. Long identities remain readable. Horizontal overflow belongs to a named data region, never the whole page.

## Tokens and component ownership

`frontend/src/styles.css` owns the incumbent palette, shell and feature layout. `frontend/src/ui.css` maps those tokens onto shadcn semantic roles and owns shared component recipes. `frontend/components.json` records the registry configuration and `@/` aliases. Tailwind v4 runs through the Vite plugin, with theme and utility imports only; **do not add Preflight or another global reset**. Legacy native-control rules exclude elements with `data-slot`; the legacy `.grid` recipe also excludes shadcn slots. This prevents cascading conflicts with component utilities.

| Role | Dark | Light |
| --- | --- | --- |
| Background (`--bg`) | #0c111b | #f3f6fa |
| Panel (`--panel`) | #141d2b | #ffffff |
| Text (`--text`) | #edf3fb | #16243a |
| Secondary text (`--muted`) | #9aaac0 | #52647b |
| Accent (`--accent`) | #6daaff | #175dc2 |
| Control boundary (`--control-border`) | #56667e | #7c8ca3 |

Semantic roles are aliases, not an independent palette: `background` → `--bg`, `foreground` → `--text`, `primary` → `--accent`, `primary-foreground` → `--on-accent`, `muted`/`secondary` → `--panel-hover`, `muted-foreground` → `--muted`, `input` → `--control-border`, and `destructive` → `--red`. In particular, do not overwrite the existing `--muted` or `--accent` with shadcn preset values. Both themes follow the existing root `data-theme` attribute, including portalled dialogs.

Keep the Inter/system sans stack without font downloads. Body text is 14px, supporting text 12–13px, section headings 18px, and page headings 29px (25px on phones). Phone inputs use 16px. Numeric comparisons use tabular figures; identifiers and code use monospace. Use the 4px spacing scale, 8px control radius, and 12px panel radius.

### Shared primitives

- Import `Button`, `Badge`, `Input`, `NativeSelect`, `Field`, `FieldGroup`, `FieldSet`, `Table`, `Tabs`, `Collapsible`, `Dialog`, `AlertDialog`, `ScrollArea`, `Separator`, `Skeleton`, `Alert` and `Empty` from their individual `components/ui` modules as needed.
- `Button` defaults to the primary action. Use `variant="outline"` for routine actions, `variant="destructive"` for dangerous actions, and `asChild` for links. Do not combine these with the legacy `.button`, `.primary` or `.danger` recipes. Keep icons at the shared 16px size, with `data-icon="inline-start"` where applicable.
- Controls and checkbox hit targets are at least 44 × 44px. Pending labels reserve width, expose `aria-busy`, and prevent duplicate submissions. All controls retain hover, focus and disabled feedback; reduced motion is respected.
- Use `NativeSelect` for the current small option lists; it retains platform keyboard behavior. Visible `FieldLabel` labels may wrap controls. Validation uses `data-invalid` on `Field`, `aria-invalid` on the input, and an associated `FieldError`.
- `Disclosure` composes shadcn Collapsible with a full-width, named button. It keeps content mounted with `forceMount` and hides it with `hidden`. Use it for device metric groups, diagnostics, tools and operation/session results.
- `Confirmation` composes AlertDialog with a title and description. Focus starts on the first action, so place Cancel first. Escape delegates to the caller's cancellation policy; pending setup/TCP work cannot dismiss the confirmation. Closing restores the captured opener, including StrictMode. Screenshot preview uses Dialog with its own title and focus return.
- Add components with `cd frontend && npx shadcn@latest add <component>`. Inspect the installed API and diff before updating. Keep `cn()` local to `lib/utils.ts`; retain token aliases and touch sizes. Install only components needed by a task.

## Device workspace

The page reads: compact identity/connection header and Manage device → one telemetry freshness area with Refresh status → Overview / History / Device tools tabs. Connection status and collection freshness are independent. A failed connection check withholds cached current values. The successful collection timestamp appears once; last-seen belongs in identity diagnostics. Paused refresh identifies the saved collection without calling it current.

Overview shows up to four available key observations, then Performance, Memory & storage, Battery & thermal and Network disclosures. Identity/capabilities and missing sources remain secondary. Missing means “not observed,” not necessarily “unsupported,” and never becomes zero. Keep real zeros and cumulative network counters. Unsupported, stale, disconnected, loading, empty and failed requests remain distinguishable.

History starts loading on first selection, retains its range across tab changes, and keeps existing charts, observation tables, recorded runs and exports. Preserve chart gaps and units. Tools contain Live screen, Terminal, Device controls, and Setup & connectivity. Existing optional setup is separate from ADB monitoring.

Workspace and terminal TabsContent are force-mounted and explicitly hidden when inactive. Tool disclosures also remain mounted. Switching tabs or collapsing a tool neither starts nor terminates sessions. Live-screen state and the open terminal-tab count remain visible in the workspace tab and tool summaries. Stop stream and Close session are the explicit termination actions. Route/auth cleanup, WebSocket/decoder disposal, cancellation, limits and the terminal ResizeObserver remain owned by the tools. Browser-tab hiding retains the screen player's existing stop policy.

## Actions, rows and scrolling

Keep local actions beside the content they control. Use `.device-actions`, `.device-form-row`, and `.device-action-group` for aligned task groups. Inspection, screen power, restart, application actions, terminal editing, and session termination stay separate. Restarts use a Separator and confirmation. Forms align their buttons to the control edge and stack on phones. Avoid adding new action bars to unrelated pages.

Observation and identity pairs remain definition lists. Scalar observations use stable number/unit columns; textual states align left, numbers align right, and composite durations remain complete. Applications and chart observations use shadcn Table with table semantics, stable columns and sticky headings. Applications stack into labelled blocks on phones. Operations and sessions remain lists, with aligned state/duration/action slots. Long names, capabilities and values wrap without hiding important content.

`ListRegion` composes ScrollArea with a naturally sized viewport capped at `min(28rem, 55svh)` (`min(24rem, 55svh)` on phones). Headings, counts and filters stay outside. The viewport is a named, focusable region with inset focus, visible scrollbars and an actual-overflow continuation hint. Polling never sets scroll position. A nested ListRegion defers scrolling to its outer region; Table does not add a second overflow wrapper. Wheel, touch and keyboard scrolling use the viewport. No virtualization is needed for the current lists.

## Shell and validation

Navigation exposes the current route; mobile navigation closes on selection and returns focus on Escape. Route changes reset scroll, focus main content and update the page title. Keep explicit access requirements and authenticated requests. State always includes text, not color alone.

See [UI review and validation](docs/UI_REVIEW.md) for completed checks and hardware/browser limitations. Run frontend tests, lint, typecheck and build after migration work, and inspect both themes at phone, tablet and desktop sizes. Recheck representative legacy routes after shared CSS changes.
