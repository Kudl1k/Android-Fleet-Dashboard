from android_fleet.terminal.manager import TerminalManager


def render(manager: TerminalManager) -> str:
    lines = []
    for key, value in manager.metrics().items():
        name = f"android_fleet_terminal_{key}"
        kind = "gauge" if key.startswith("active_") else "counter"
        lines.extend([f"# TYPE {name} {kind}", f"{name} {value}"])
    return "\n".join(lines) + "\n"
