# M6 physical input acceptance plan

Status: **BLOCKED pending explicit user approval and a user-prepared harmless screen.**
No approval for input or physical rotation is implied by view-only streaming.

Prepare an isolated disposable browser test page manually on the Samsung, with an
empty text field, a tap counter, a draggable box and a scrollable area. It must contain
no private data or links to private applications. No application installation is needed.
The operator must confirm the foreground screen and approve the actions below before
any input is injected. If a suitable screen is unavailable, hardware acceptance stays
pending; automated fixtures remain the acceptance evidence.

| Action | Expected effect | Recovery |
| --- | --- | --- |
| One tap in the counter | Counter increments once | Reload disposable page |
| Hold blank page area for 700 ms, then release | Long press delivered; possible context menu | Back dismisses menu |
| Swipe scroll area vertically | Only test content scrolls | Scroll back or reload |
| Drag test box from marked start to finish | Box moves to target | Reload page |
| Tap empty field and type `M6 test 123` | Exact text appears in disposable field | Reload page |
| Back once | Keyboard/menu closes or browser leaves test page | User manually reopens page |
| Home once | Launcher appears | User manually returns to browser |
| Recent apps once | Overview appears; do not inspect cards or capture screenshots | Home, then user manually returns |
| Two authenticated viewers request control | First succeeds; second gets conflict | Release first; verify second can acquire |
| Disconnect owning browser with no keys or pointers held | Control released; no automatic reacquisition | View-only reconnect, explicit acquisition only |

Abort immediately if the foreground differs from the approved test screen, a private
screen appears, coordinates are uncertain, or geometry changes. Stop the stream and
release control; the user restores the foreground manually. Do not open other apps,
change security/account settings, install/uninstall, reboot or delete data. No stream
pictures or entered text are written into acceptance artifacts.

Physical portrait/landscape acceptance requires a separate explicit approval to
manually rotate the phone while this test page is visible. No rotation setting will be
changed. Synthetic SPS and browser geometry fixtures cover unapproved rotations.
