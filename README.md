# TeeEmpire — multi-brand t-shirt automation

A pluggable, brand-scoped pipeline that takes a list of meme/handle seeds and
walks them through:

1. **plan** — generate Concepts (title, tagline, design brief, tags, safety notes)
2. **design** — pick a palette + render a shirt mockup PNG
3. **list** — push to Printify and Etsy as drafts
4. **review** — Telegram card to a brand-specific reviewer chat with ✅ / ❌ / ✏️ buttons
5. **ship** — on approval, publish/activate the listings

Built around the earl-biggers Phase 1 scaffold (Printify + HITL + concept
generator) and the Nickle Ts brand brief, refactored into a multi-brand,
multi-platform architecture with a SQLite event store.

## Quick start

```bash
# 1. List configured brands
python3 -m empire.cli brands

# 2. Bootstrap with the existing earl-biggers fixtures (45 concepts, 15 designs)
python3 -m empire.cli import --source /app/cc/sources/earl-biggers

# 3. Generate fresh concepts for one lane (dry-run, no APIs needed)
python3 -m empire.cli plan --brand earl_biggers --lanes force_multipliers --per-lane 3

# 4. Build mockups for every stored concept
python3 -m empire.cli design --brand earl_biggers

# 5. Create draft listings (dry-run unless --live)
python3 -m empire.cli list --brand earl_biggers --platform both

# 6. Full pipeline end-to-end
python3 -m empire.cli run --brand nickle_ts --per-lane 2 --skip-reviews

# 7. Status / analytics
python3 -m empire.cli status
python3 -m empire.cli analytics
```

## Layout

```
empire/
├── brands/
│   ├── earl_biggers/   brand.yaml + lanes/*.json seed lists
│   └── nickle_ts/      brand.yaml + lanes/*.json
├── core/
│   ├── models.py       dataclasses (Brand, Concept, Design, Listing, Sale)
│   ├── store.py        SQLite (data/empire.db) — idempotent upserts
│   ├── brands.py       brand + lane loader
│   ├── concepts.py     XAI/Grok or template concept generator
│   ├── images.py       pluggable image backend (placeholder/openai/comfyui)
│   ├── designs.py      Pillow-based shirt mockup compositor
│   ├── printify.py     Printify v1 client
│   ├── etsy.py         Etsy Open API v3 client (OAuth + listings)
│   ├── hitl.py         multi-brand Telegram review bot
│   ├── analytics.py    revenue / funnel / top sellers
│   ├── orchestrator.py end-to-end pipeline runner
│   └── fixtures.py     legacy earl-biggers importer
├── cli.py              `python -m empire.cli <command>`
├── cron/crontab.template
├── data/               empire.db + mockups/ + runs/
├── tests/
├── .env.example
└── README.md
```

## Dry-run vs live

Every external integration (Printify, Etsy, OpenAI, ComfyUI, Telegram) accepts a
`dry_run` flag. The CLI defaults to **dry-run** — all writes are simulated and
the SQLite store gets synthetic IDs. Pass `--live` on `plan`/`design`/`list`/
`review`/`run` to actually hit external APIs (and only after filling in `.env`).

## Adding a new brand

1. Create `brands/<slug>/brand.yaml` (voice, palette, lanes, shop IDs).
2. Add `brands/<slug>/lanes/<lane>.json` seed lists (`{"lane": ..., "seeds": [...]}` ).
3. `python3 -m empire.cli plan --brand <slug>` and onward.

Voice tuning happens in `core/concepts.py::_voiced_*` — extend the per-brand
branches with whatever house style you want.

## Image generation

`EMPIRE_IMAGE_BACKEND` selects the backend:

| backend       | requires                          | notes                              |
|---------------|-----------------------------------|------------------------------------|
| `placeholder` | nothing (Pillow optional)         | Renders the title centered on the shirt color — fine for review mockups. |
| `openai`      | `OPENAI_API_KEY`                  | Uses `gpt-image-1` via `/v1/images/generations`. |
| `comfyui`     | `COMFYUI_URL` + workflow template | Submits the workflow JSON; the orchestrator currently returns a dry-run id — finish the polling/extraction in your workflow handler. |

For real production designs, wire ComfyUI on `192.168.1.206` (it's installed
under `/app/giles/comfyui`).

## Etsy auth

```python
from empire.core.etsy import EtsyClient
info = EtsyClient.build_authorize_url(client_id="...", redirect_uri="...")
print(info["url"])         # open in browser
# after redirect, exchange the code:
tokens = EtsyClient.exchange_code(client_id="...", redirect_uri="...",
                                  code="<from-callback>",
                                  code_verifier=info["code_verifier"])
# tokens["access_token"] -> ETSY_OAUTH_TOKEN
# tokens["refresh_token"] -> refresh via EtsyClient.refresh()
```

## Tests

```bash
cd /app/cc && python3 -m unittest discover -s empire/tests
```

All tests run dry-run; no network or credentials required.

## What changed from earl-biggers Phase 1

| earl-biggers (before)                               | TeeEmpire (now)                                   |
|-----------------------------------------------------|---------------------------------------------------|
| Single brand, hardcoded paths to `/home/jimmer/...` | N brands; all paths relative to package          |
| 2 hardcoded lanes, copy-pasted prompts              | YAML brand configs + JSON lane seeds              |
| JSON files on disk only                             | SQLite store with upsert + analytics              |
| Placeholder mockup URL                              | Pillow-composited shirt mockup PNG                |
| Etsy = 25-line stub                                 | Real Etsy Open API v3 client (OAuth + listings)   |
| Printify hardcoded `placehold.co` images            | Uploads the actual mockup bytes                   |
| Telegram bot single-chat                            | Multi-brand routing by `review_chat_id`           |
| No analytics                                        | Funnel + top sellers + revenue                    |
| One-shot CLI                                        | Crontab template; idempotent steps                |
```
