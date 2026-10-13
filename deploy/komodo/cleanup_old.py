"""Remove only inventoried old containers after explicit downtime confirmation."""

import argparse
import json
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirmed-downtime", action="store_true", required=True)
    parser.parse_args()
    inventory = json.loads(
        Path(__file__).with_name("deployment-inventory.json").read_text()
    )
    expected = {item["Id"] for item in inventory}
    docker = ["docker", "--context", "colima"]
    actual = set(
        subprocess.check_output(
            docker
            + [
                "ps",
                "-aq",
                "--no-trunc",
                "--filter",
                "label=com.docker.compose.project=adb-dashboard",
            ],
            text=True,
        ).split()
    )
    if actual != expected:
        raise SystemExit("Project membership changed; re-inspect before cleanup.")
    inspected = json.loads(
        subprocess.check_output(docker + ["inspect", *sorted(expected)])
    )
    for item in inspected:
        labels = item["Config"]["Labels"]
        if (
            labels.get("com.docker.compose.project") != "adb-dashboard"
            or labels.get("com.docker.compose.project.working_dir")
            != "/Users/homelab/Development/adb-dashboard"
            or labels.get("com.docker.compose.project.config_files")
            != "/Users/homelab/Development/adb-dashboard/docker-compose.yml"
        ):
            raise SystemExit("Labels changed; refusing removal.")
    print(
        "Stopping and removing four inventoried containers; service downtime starts now."
    )
    subprocess.run(docker + ["stop", "--time", "30", *sorted(expected)], check=True)
    subprocess.run(docker + ["rm", *sorted(expected)], check=True)


if __name__ == "__main__":
    main()
