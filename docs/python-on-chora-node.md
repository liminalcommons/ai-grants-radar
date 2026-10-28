# Python on chora-node: the rules every agent follows

This applies to every agent and session that installs, runs or changes Python on chora-node, in
any project. It was set 2026-10-26 by Victor, after the sec-audit
([tools/sec-audit/](../../tools/sec-audit/README.md)). The box had 5 base Pythons, 19
environments and 307 packages installed globally, and nobody could say what needed what.

The consolidation is **in progress**. The rules below hold now, for new work and for anything you
touch. The [not yet migrated](#not-yet-migrated) section lists what still breaks them, so you
neither add to it nor "fix" it on the side.

## The rules

1. **uv is the only tool for Python environments and packages.** Don't use pip, pipx, conda,
   poetry or virtualenv for project work.
2. **Nothing is installed globally.** Never `pip install` into Store Python, python.org 3.11 or
   any conda base, and never `pip install --user`. If something needs a package, it belongs to a
   project or a uv tool (rule 7).
3. **Every project that runs has the same four files:**
   - `pyproject.toml`
   - `uv.lock`, committed
   - `.python-version`
   - a `.venv\` inside the project folder, which is never committed

   Start one with `uv init --app`. Build it with `uv sync --locked`, and run it with
   `uv run --locked …`.
4. **Python itself comes from uv:** `uv python install 3.12`. New projects use **3.12** unless
   they need something else. Don't install Python from python.org, the Store, winget or conda. In
   `pyproject.toml`:
   ```toml
   [tool.uv]
   python-preference = "only-managed"
   exclude-newer = "7 days"
   ```
5. **The cooldown: no package version under a week old.** `exclude-newer = "7 days"` above
   enforces it. Both 2026 LiteLLM compromises were bad releases that were pulled within hours, so
   a week's delay would have avoided both. To take a newer version of one package for a security
   fix, use `exclude-newer-package = { "<pkg>" = "<date>" }` and give the reason in the commit
   message.
6. **Upgrades go through the lock, never in place:**
   1. Run `uv lock --upgrade-package <pkg>`, or `uv lock --upgrade` to upgrade everything.
   2. Read the diff.
   3. Scan it with `osv-scanner scan source -L uv.lock`.
   4. Run `uv sync --locked`, test, and commit the lock.

   Never run pip inside a `.venv`. A broken environment is deleted and rebuilt from the lock.
   osv-scanner is not installed yet. Install it once with
   `winget install --id Google.OSVScanner --exact`.
7. **One-off command-line tools:**
   - for a tool you keep, `uv tool install <pkg>==<version>`;
   - for a single use, `uvx <pkg>@<version>`;
   - for a script, PEP 723 inline metadata plus `uv run script.py`.
8. **Anything that runs unattended names its interpreter by absolute path.** That covers
   services (NSSM), scheduled tasks, Startup items and watchdogs. Use either:
   - `C:\path\to\project\.venv\Scripts\python.exe -m <module>`, or
   - `uv run --project C:\path\to\project --locked <cmd>`.

   Never a bare `python` or `py` (they resolve to whatever is on PATH that day), and never
   `uv run --with <pkg>` (that is an unpinned environment).
9. **Which uv.** The standard is `C:\Users\choranode\.local\bin\uv.exe`. Today a bare `uv`
   resolves to **Hermes's own copy** (`%LOCALAPPDATA%\hermes\bin\uv.exe`, 0.12.11), which is
   first on PATH, while the standard one is 0.10.5. Lockfiles from different uv versions can
   churn. Until the standard uv is updated and moved ahead on PATH, call it by full path in
   anything you commit or schedule.
10. **Untrusted input:** run Python that reads downloaded files with `-I`, from an empty folder,
    with the files passed in as arguments.

## Leave these alone

These are documented exceptions. Don't install into them, upgrade them or "consolidate" them
without the owner's word.

| What | Why |
|---|---|
| `C:\Users\choranode\miniforge3\envs\ryzen-ai-py312` | Runs the **Parakeet** speech-to-text service and the VibeCafe transcript server (:8775). AMD's RyzenAI SDK pins it, and its onnxruntime split-install breaks on restart. No `conda update`, no pip. Changes go through its `repair-and-restart.ps1`. Miniforge itself is not upgraded either, because this env lives inside it. |
| `%LOCALAPPDATA%\hermes\` | Hermes ships its own Python 3.14 and uv, and its updates manage them. |
| `%APPDATA%\uv\tools\*` (browser-use, ruff) | uv tools. Update them only with `uv tool upgrade <name>`. |

## Not yet migrated

These still break the rules. If your work touches one, migrate it (rules 3–8) as part of that
work and say so. Otherwise leave it, and don't add packages to it.

| What | Used by | Moves to |
|---|---|---|
| **Store Python 3.13** (the default `python`), **307 user-site packages** | village-os: `village_voice` (×4), `village_os.record.mcp`, an `http.server` on :4871, the `village-patrol-watchdog` task (bare `python`), and `village_os.app` via `uv run --with …` | village-os's own `uv.lock` and `.venv`; then the global packages are removed |
| **python.org 3.11** (49 global packages, including torch) | `village-os-day\owl-voiceid` on :3124 (`py -3.11 -m uvicorn`) | owl-voiceid's own project env; then 3.11 is uninstalled |
| `C:\tools\miniconda` (and its `bitnet` env), `~\.conda\envs\luxtts` | nothing found running | deleted once Victor labels them dead |

## Before you call Python work done

- [ ] `uv sync --locked` passes from a clean checkout, and `uv.lock` is committed.
- [ ] `osv-scanner scan source -L uv.lock` shows no malicious (`MAL-`) entries and no actively
      exploited ones.
- [ ] Nothing was installed globally: `py -3.13 -m pip list --user` and
      `py -3.11 -m pip list` show the same counts as before you started.
- [ ] Every service or task you added or changed points at a project `.venv` or uses
      `uv run --project … --locked`.

## Supply-chain incidents

If a package anywhere on the box is reported compromised, answer "are we hit?" the same day.
Run `py -3.13 -I C:\Users\choranode\code\chora-workspace-victor\tools\sec-audit\inventory.py`,
then search `results\<day>\inventory.json` for the package. It lists every environment's
packages, read from disk.
