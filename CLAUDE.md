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

**Print scale on wrap products — the gotcha.** Printify's `scale` is a fraction of
the print-area *width*, and on drinkware that width is the whole circumference
(bottle 887/provider 23: 2759×1500 px, aspect 1.84). Only about a third of it
faces the buyer. So for **square** art the default `SCALE["bottle"] = 0.6` both
overflows the 1500 px height and wraps two-thirds of the design around the back.
Square lockups want **~0.33**; verified on the AU2 bottle.

Re-scale in place rather than creating a second product — and **pass `--scale`
explicitly**, since `--update` on its own falls back to the same 0.6 default that
caused the problem:

```bash
./.venv/bin/python scripts/publish_merch_draft.py --brand au2 --product bottle \
  --design data/art/<art>.png --slug <slug> --name "<Title>" --price 28 \
  --scale 0.33 --update <product_id>
```

Mockup freshness is confirmed by **hashing the image bytes**: Printify re-renders
behind the *same* `src` URL, so a URL comparison silently passes stale images. If
the re-render hasn't landed within `--poll`, the script downloads nothing and
exits 4 rather than filing the old render under the new slug.

Prefer this over `publish_merch_single.py` / `publish_store.py` for anything that
isn't Madd Hatchery — both are hardcoded to that storefront, crash if `.env` is
missing, and shell out to a `rembg` venv that isn't installed.

## POD partner — Printify, single source

**Printify is the POD partner for everything**: apparel, drinkware, stickers,
posters. It has a public REST API, so every stage stays scriptable end to end.

Tapstitch was evaluated and **dropped** (2026-09-27) — it has no public developer
API, so apparel through it could never be a scripted pipeline stage. Do not
reintroduce a second POD partner without a written API contract to build against.

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
| ~~TE-9~~ | **CLOSED 2026-09-27** — apparel stays on Printify; Tapstitch dropped, so there is no second connector to collide with `core/etsy.py`. |
| ~~TE-10~~ | **ANSWERED 2026-09-23** — "we have no connection to nor dependency to floor2 or .206". `core/mission_control.py`, the `mc-publish`/`mc-poll`/`mc-open` commands, the `--no-publish` flags and the `.local81` sync scope are all removed. `empire gate` (`core/local_approval.py`) is now the only approval gate. |

## Constraints (inherited — non-negotiable)

- Automation belongs in `.claude/skills/`, not app code — see TE-4.
- No auth, no multi-user, no deployment scaffolding.
- **Nothing publishes to Printify-live or Etsy without a human gate**, including
  "just for a test run". Creating a draft is fine; `publish_product()` is not.
