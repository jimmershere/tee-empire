# CLAUDE.md — Tee Empire / Portwright Press (`/app/tee-empire`)

> **Cloned and running on pop-os as of 2026-09-11.** Everything below is observed
> in the working tree or returned by an API, not inferred. The previous version of
> this file described an empty placeholder folder — that was wrong by a wide
> margin. Setup detail: [`docs/fleet-setup.md`](docs/fleet-setup.md).

## Project

Multi-brand print-on-demand merch automation: concept → image → Printify/Etsy →
human review. Fleet context and constraints: [`../CLAUDE.md`](../CLAUDE.md).

**Name drift:** `pyproject.toml` calls this **Portwright Press**; commit #9 was
"Rebrand to Portwright Press". The git remote is still `jimmershere/tee-empire`.
Both names are live — don't "fix" one to the other without asking. This is also
the first hard evidence bearing on workspace question **P-1** (what Portwright is).

## What is here

| | |
|---|---|
| Remote | `github.com/jimmershere/tee-empire` — **public** |
| Runtime | Python 3.9+; deps are only `flask`, `Pillow`, `PyYAML` |
| Venv | `.venv/` (gitignored) — this box has no system pip, see fleet-setup |
| Tests | `./.venv/bin/python -m unittest discover -s tests -t .` → 13 pass |
| Brands | `earl_biggers`, `madd_hatchery`, `nickle_ts` |
| Review gate | `python3 -m empire gate --port 3333` (Flask, localhost) |

`core/` holds the pipeline: `printify.py`, `etsy.py`, `images.py`, `concepts.py`,
`judge.py`, `hitl.py`, `orchestrator.py`, `store.py`, and others.

## Live accounts (TE-3, partially answered)

`brands/earl_biggers/brand.yaml` names a real shop: **Printify `27415408`,
"EarlBiggersDammit (Etsy-linked)"**. So Printify→Etsy is wired on the Printify
side for Earl Biggers. `etsy_shop_id` is still `null`.

Still unknown: whether any listing has ever gone live, and revenue (TE-2).

## Public repo — treat as such

`.env` is gitignored and mode 600. Keys in a commit are an incident, not a
cleanup task. `au2-logo-fun.png`, `CLAUDE.md` and `.venv/` are held out of git via
`.git/info/exclude` so workspace-local files can't be pushed by accident.

## Merch drafts — the safe path

[`scripts/publish_merch_draft.py`](scripts/publish_merch_draft.py) creates a
Printify **draft** (`visible: False`) for a bottle / mug / sticker and downloads
the rendered mockups to `data/mockups/<slug>/`. It never calls
`publish_product()`, makes **no AI API calls**, and needs no `rembg`.

```bash
./.venv/bin/python scripts/publish_merch_draft.py --brand earl_biggers \
  --product bottle --design data/art/au2-logo-fun.png --slug au2-bottle \
  --name "Appearance Unlimited — Stainless Water Bottle" --price 28 --dry-run
```

Blueprints verified against Printify's public catalog: **887** Stainless Steel
Water Bottle · **478** Ceramic Mug · **400** Kiss-Cut Stickers · **12**
Bella+Canvas 3001 · **6** Gildan 5000.

Prefer this over `publish_merch_single.py` / `publish_store.py` for anything that
isn't Madd Hatchery — both are hardcoded to that storefront, crash if `.env` is
missing, and shell out to a `rembg` venv that isn't installed.

## Apparel / Tapstitch

**Tapstitch has no public developer API** — it cannot be a scripted pipeline
stage. Full finding and the three options: [`docs/tapstitch.md`](docs/tapstitch.md).

## Open conflict — TE-4 is confirmed, not hypothetical

App code calls LLM/image APIs directly, against the fleet's *don't build your own
agent* rule: `core/judge.py:22` → `api.anthropic.com`, `core/concepts.py:23` →
`api.x.ai`, `core/images.py` → OpenAI / OpenRouter / kie.ai. `skills/image_craft/`
exists, so the migration has started. **A design decision, not a bug to silently
fix** — raise it, don't patch it.

## Open questions — do not guess

| # | Question |
|---|---|
| TE-1 | Repo is clearly working, not abandoned — but how much has ever run end to end against a live shop? |
| TE-2 | Which brands are selling today? Any revenue? |
| TE-3b | Is the Etsy side live for Earl Biggers, and who holds the Etsy OAuth token? |
| TE-4b | Resolve the agent-in-app-code conflict: finish the move into `skills/`, or grant an exception? |
| TE-6c | Clone on quasimodo too, or leave pop-os as the only working host? No GPU need either way. |
| TE-7 | Should Northern Michigan merch reuse this pipeline as another brand? (= NMM-6) |
| TE-9 | If apparel moves to Tapstitch, who owns the Etsy listing — Tapstitch's connector or `core/etsy.py`? |
| ~~TE-10~~ | **ANSWERED 2026-09-23** — "we have no connection to nor dependency to floor2 or .206". `core/mission_control.py`, the `mc-publish`/`mc-poll`/`mc-open` commands, the `--no-publish` flags and the `.local81` sync scope are all removed. `empire gate` (`core/local_approval.py`) is now the only approval gate. |

## Constraints (inherited — non-negotiable)

- Automation belongs in `.claude/skills/`, not app code — see TE-4.
- No auth, no multi-user, no deployment scaffolding.
- **Nothing publishes to Printify-live or Etsy without a human gate**, including
  "just for a test run". Creating a draft is fine; `publish_product()` is not.
