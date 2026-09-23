# tee-empire on the fleet — how it should be set up

Research answer for "how best to set up tee-empire using fleet / quasimodo /
pop-os". Written 2026-09-11. Everything below is **observed on pop-os** unless
labelled otherwise.

## TL;DR

Sync tee-empire with **git, not rsync**. It is the only venture under `/app` with
a real upstream repo, which makes the workspace's delete-hazard rule moot for it —
and rsync would be strictly worse. Clone on whichever host you work from; both is
fine. Keep `.env` out of every sync path.

---

## 1. What was actually found

| Claim in `tee-empire/CLAUDE.md` (before this session) | Reality |
|---|---|
| "Placeholder folder … not cloned on either host" | Repo is substantial and now cloned at `/app/tee-empire` on pop-os |
| "Current contents: nothing but this file" | 13 modules under `core/`, 3 brands, a CLI, a Flask gate, tests |
| "unverified whether it has ever published a live listing" | `brands/earl_biggers/brand.yaml` names a live shop: **Printify 27415408, "EarlBiggersDammit (Etsy-linked)"** |
| Project name "Tee Empire" | `pyproject.toml` says **Portwright Press**; commit #9 is "Rebrand to Portwright Press". The git remote is still `tee-empire`. |

The repo is Python 3.9+, deps are only `flask`, `Pillow`, `PyYAML`. All 13 tests
pass on pop-os. `python3 -m empire brands` lists `earl_biggers`, `madd_hatchery`,
`nickle_ts`.

## 2. The sync question — use git

The workspace rule is *never `rsync --delete` toward the host that holds the only
copy*. For tee-empire there is no "only copy": GitHub holds it. So:

- **Do not** add `/app/tee-empire` to `poplab/local81/playbooks/fleet-sync.yml`.
- Each host runs `git clone https://github.com/jimmershere/tee-empire.git /app/tee-empire`
  and `git pull`. Divergence is visible and recoverable; rsync divergence is not.

Two corrections to the workspace `CLAUDE.md` that came out of this:

1. **The stated delete hazard is out of date.** `fleet-sync.yml` today mirrors only
   `/app/poplab/` (`delete: true`) and `/app/docs/` (`delete: false`). There is no
   `/app/portwright` entry any more, and nothing references tee-empire.
2. ~~**There is a third host.**~~ **Resolved 2026-09-23 (TE-10).** The scope that
   pushed `.` to `floor2` with `rsync -az --delete` is gone, along with
   `core/mission_control.py` and the `mc-*` commands. jimmer confirmed there is no
   connection to nor dependency on floor2/.206. tee-empire now runs on pop-os only
   and is deployed nowhere.

## 3. Which host to run it on (TE-6b)

**Either. There is no GPU dependency.** Image generation backends are all remote
HTTP APIs — kie.ai, OpenRouter, OpenAI — with ComfyUI as an *optional* backend
pointed at a URL (`COMFYUI_URL`). Nothing runs a local model.

Practical split:

- **pop-os** — controller, already set up, runs the Flask review gate on
  `127.0.0.1:3333`. Good default.
- **quasimodo** — holds the other ventures' code. Only worth a clone if you want
  to run drops there too. It is *not* a source of truth for this venture.

Because pop-os runs no `sshd`, anything on quasimodo has to pull for itself —
another reason git beats rsync here.

## 4. Setup actually performed on pop-os

```bash
git clone https://github.com/jimmershere/tee-empire.git /app/tee-empire
cd /app/tee-empire
python3 -m venv .venv          # note: this box has no pip/ensurepip;
                               # pip was bootstrapped via get-pip.py
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env           # then fill PRINTIFY_API_KEY
./.venv/bin/python -m unittest discover -s tests -t .   # 13 passed
```

**Gotcha worth recording:** this machine has no system `pip` and no `ensurepip`
module, so `python3 -m venv` produces a venv without pip. Bootstrap it with
`https://bootstrap.pypa.io/get-pip.py`, or `apt install python3-pip python3-venv`.

`rembg` is referenced by `scripts/publish_store.py` and
`scripts/publish_merch_single.py` via a **separate venv** at `~/.venvs/rembg`
(`REMBG_PY`). It is not in `requirements.txt` and is not installed. It is only
needed to knock backgrounds out of *mockups*; it is not needed for print art that
is already transparent. `scripts/publish_merch_draft.py` avoids it entirely.

## 5. Credentials

`.env` is gitignored (`.gitignore:1`) and now mode 600. The repo is **public** —
per `CLAUDE.md`, a key in the history is an incident, not a cleanup task. The
local81 rsync scope already excludes `.env`; keep it that way.

Only `PRINTIFY_API_KEY` is needed to create drafts. Etsy keys are not required —
drafts never touch Etsy.

## 6. Open conflict — TE-4 is real, and unresolved

The fleet constraint *"don't build your own agent — no embedded LLM API calls in
application code"* **is currently violated**. Confirmed outbound calls from app
code:

| File | Endpoint |
|---|---|
| `core/judge.py:22` | `https://api.anthropic.com/v1/messages` |
| `core/concepts.py:23` | `https://api.x.ai/v1/responses` |
| `core/images.py` | `api.openai.com`, `openrouter.ai`, `api.kie.ai` |

`skills/image_craft/` exists, so migration toward the approved shape has started
but is not finished. `CLAUDE.md` says this is *a design decision, not a bug to
silently fix* — so it is recorded here and left alone.

**It does not block merch work.** `scripts/publish_merch_draft.py` makes no AI
calls at all; it is pure Printify REST.

## 7. Printify vs Tapstitch — they are not interchangeable

See [`tapstitch.md`](tapstitch.md). Short version: Printify has a public REST API
and can be driven end to end from code. **Tapstitch has no public developer API**,
so apparel through Tapstitch cannot be a scripted pipeline stage — the last mile
is a manual dashboard upload.
