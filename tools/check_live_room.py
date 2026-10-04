"""Run two players against a real Archipelago server and check what crosses it.

Score DeathLink, score traps and the other players' scores all travel through
the server, so unit tests cannot see them break. This generates a two-player
AP_10 seed in a scratch folder -- never a shared Players/ folder -- hosts it,
plays both seats with the real browser client, then has the real Python client
read the room, and shuts everything down.

    python tools/check_live_room.py

Needs an Archipelago source checkout (AP_ROOT, default C:/Users/turtl/Archipelago)
with this world linked into worlds/, and node. This is the check that caught the
browser client saving before it marked a threshold handled, which made a
reconnect resend the death and refire the trap.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
AP = os.environ.get("AP_ROOT", "C:/Users/turtl/Archipelago")
PORT = 38281
YAML = """name: {name}
game: AP_10
AP_10:
  death_link: true
  score_threshold: 100
  score_traps: true
  store_slots: 6
  checks_per_phase: 2
"""


def python_client_reads_the_room() -> list[str]:
    """Log in as Bob with the real Python client; return what failed."""
    sys.path.insert(0, AP)
    os.chdir(AP)
    import ModuleUpdate
    ModuleUpdate.update_ran = True
    from CommonClient import server_loop
    from worlds.phase10.client.context import Phase10CommandProcessor, Phase10Context

    failures: list[str] = []

    async def run() -> None:
        ctx = Phase10Context(f"ws://127.0.0.1:{PORT}", None)
        ctx.auth = "Bob"
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="server loop")
        ctx.client_loop = asyncio.create_task(ctx.phase10_loop(), name="phase10 loop")
        for _ in range(50):
            await asyncio.sleep(0.2)
            if any(record is not None for _, record in ctx.rivals.values()):
                break
        records = [record for _, record in ctx.rivals.values()]
        if not records or records[0] is None:
            failures.append(f"the Python client did not read Alice's score: {ctx.rivals}")
        lines: list[str] = []

        class Recorder(Phase10CommandProcessor):
            def output(self, text: str) -> None:
                lines.append(text)

        Recorder(ctx)("/scores")
        if not any(line.startswith("Alice:") for line in lines):
            failures.append(f"/scores does not list Alice: {lines}")
        await ctx.shutdown()

    asyncio.run(run())
    return failures


def main() -> int:
    if not pathlib.Path(AP).is_dir():
        print(f"! no Archipelago checkout at {AP}. Set AP_ROOT to yours.")
        return 2
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        players, out = pathlib.Path(tmp, "players"), pathlib.Path(tmp, "out")
        players.mkdir()
        out.mkdir()
        for name in ("Alice", "Bob"):
            (players / f"{name}.yaml").write_text(YAML.format(name=name))
        env = {**os.environ, "SKIP_REQUIREMENTS_UPDATE": "1"}
        subprocess.run([sys.executable, "Generate.py", "--player_files_path", str(players),
                        "--outputpath", str(out)], cwd=AP, env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        seed = next(out.glob("*.zip"))
        log_path = pathlib.Path(tmp, "server.log")
        with open(log_path, "w") as log:
            server = subprocess.Popen(
                [sys.executable, "MultiServer.py", "--port", str(PORT),
                 "--host", "127.0.0.1", "--disable_save", str(seed)],
                cwd=AP, env=env, stdout=log, stderr=log)
            try:
                for _ in range(60):
                    time.sleep(0.5)
                    if "server listening" in log_path.read_text():
                        break
                else:
                    print("! the server did not start")
                    return 1
                browser = subprocess.run(
                    ["node", "docs/test/live_room.mjs", f"ws://127.0.0.1:{PORT}"],
                    cwd=ROOT, text=True, capture_output=True, timeout=180)
                print(browser.stdout.rstrip())
                if browser.returncode != 0:
                    failures.append("the browser clients failed")
                failures += python_client_reads_the_room()
            finally:
                server.terminate()
                server.wait(timeout=10)
    for line in failures:
        print(f"FAIL  {line}")
    if not failures:
        print("\nboth clients send, receive and read each other through a real room")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
