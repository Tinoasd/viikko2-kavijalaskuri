"""Verify real application/server restarts before recording a Passed result.

Run on the Ubuntu server as root. This uses local MySQL socket authentication;
it neither asks for nor prints the application's database password.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen

STATE_DIR = Path("/var/lib/pythonapp-persistence-test")
STATE_FILE = STATE_DIR / "state.json"
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")


def command(args):
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Command failed.")
    return result.stdout.strip()


def sql(statement):
    return command([
        "mysql", "--batch", "--skip-column-names", "--database=pythonapp",
        "--execute", statement,
    ])


def literal(text):
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def record_result(kind, text):
    column = {"app": "app_restart_result", "server": "server_restart_result"}[kind]
    sql(f"UPDATE page_counter SET {column} = {literal(text)} WHERE id = 1")


def snapshot():
    for unit in ("mysql.service", "nginx.service", "pythonapp.service"):
        active = command(["systemctl", "is-active", unit])
        if active != "active":
            raise RuntimeError(f"{unit} is not active. Wait for startup to finish and try again.")

    # Verify Nginx -> Gunicorn -> Flask -> MySQL without adding a page view.
    with urlopen(Request("http://127.0.0.1/viikko2/", method="HEAD"), timeout=10) as response:
        if response.status != 200:
            raise RuntimeError("The /viikko2/ page is not responding successfully.")

    value = sql("SELECT visits FROM page_counter WHERE id = 1")
    if not value.isdigit():
        raise RuntimeError("Counter row is missing or invalid. Run schema.sql first.")
    invocation = command([
        "systemctl", "show", "pythonapp.service", "--property=InvocationID", "--value",
    ])
    if not invocation:
        raise RuntimeError("Cannot read the application's systemd invocation ID.")
    return {
        "count": int(value),
        "boot_id": BOOT_ID.read_text().strip(),
        "invocation_id": invocation,
    }


def read_state():
    if not STATE_FILE.is_file():
        return {}
    return json.loads(STATE_FILE.read_text())


def save_state(state):
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".state-", dir=STATE_DIR)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(state, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, STATE_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fail(kind, message):
    record_result(kind, "Failed. " + message)
    raise RuntimeError(message)


def check_application(before, after):
    if before["boot_id"] != after["boot_id"]:
        fail("app", "The server rebooted; this check requires an application-only restart.")
    if before["invocation_id"] == after["invocation_id"]:
        fail("app", "The application has not been restarted since the checkpoint.")
    if after["count"] < before["count"]:
        fail("app", "The counter decreased after the application restart.")


def check_server(before, after):
    if before["boot_id"] == after["boot_id"]:
        fail("server", "The server has not rebooted since the checkpoint.")
    if after["count"] < before["count"]:
        fail("server", "The counter decreased after the server reboot.")


def run(action):
    if action == "before-app":
        current = snapshot()
        if current["count"] < 1:
            raise RuntimeError("Open /viikko2/ at least once before testing persistence.")
        save_state({"app_before": current, "app_passed": False})
        record_result("app", "Pending. Waiting for an application restart and verification.")
        record_result("server", "Not tested yet.")
        print(f"Checkpoint saved: {current['count']} page views.")
        print("Next: sudo systemctl restart pythonapp")
        print("Then: sudo python3 /opt/pythonapp/persistence_test.py after-app")
        return

    state = read_state()
    if action == "after-app":
        if "app_before" not in state:
            raise RuntimeError("Run before-app first.")
        current = snapshot()
        before = state["app_before"]
        check_application(before, current)
        text = (
            f"Passed. {before['count']} page views before and {current['count']} "
            "after restarting the application. The counter was retained."
        )
        record_result("app", text)
        state.update(app_passed=True, app_after=current)
        save_state(state)
        print(text)
        return

    if action == "before-reboot":
        if not state.get("app_passed"):
            raise RuntimeError("Complete before-app and after-app before the server reboot test.")
        current = snapshot()
        if current["count"] < 1:
            raise RuntimeError("The counter must be greater than zero before testing.")
        state["server_before"] = current
        state["server_passed"] = False
        save_state(state)
        record_result("server", "Pending. Waiting for a server reboot and verification.")
        print(f"Checkpoint saved: {current['count']} page views.")
        print("Next: sudo reboot")
        print("After reconnecting: sudo python3 /opt/pythonapp/persistence_test.py after-reboot")
        return

    if action == "after-reboot":
        if "server_before" not in state:
            raise RuntimeError("Run before-reboot first.")
        current = snapshot()
        before = state["server_before"]
        check_server(before, current)
        text = (
            f"Passed. {before['count']} page views before and {current['count']} "
            "after rebooting the server. The counter was retained."
        )
        record_result("server", text)
        state.update(server_passed=True, server_after=current)
        save_state(state)
        print(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("before-app", "after-app", "before-reboot", "after-reboot"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run with sudo python3.")
    try:
        run(args.action)
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
