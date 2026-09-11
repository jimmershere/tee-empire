# Portwright Press — local usage (drop → .206 approval → Etsy)

> A Portwright product (Built in Port · Proven at Sea). The `empire` CLI command
> and `EMPIRE_*` env prefix are unchanged.

The pipeline: **drop an image and/or prompt into `inbox/` → it fans out into a
merch bundle (1 tee listing with 7 color variants × all sizes, 15oz mug, 4"
sticker, 11×14 poster) → drafts post to the .206 Mission Control approval UI →
you review / refine / approve → approved items publish to Printify, which syncs
to Etsy.**

> Etsy is reached via **Printify → Etsy sales-channel sync**, not the Etsy API.
> Printify shop `27415408` is connected to Etsy; publishing on Printify pushes
> the listing to the EarlBiggers Etsy storefront automatically.

## One-time setup
```bash
cd /app/tee-empire
python3 -m pip install -r requirements.txt   # or: --break-system-packages flask pillow
# .env is already populated (PRINTIFY_API_KEY, OPENROUTER_API_KEY, MC_* for .206).
```
Run everything as `python3 -m empire <command>`.

## Daily flow

### 1. Drop art / prompts
Put files into `inbox/`. Each "drop" is grouped by filename stem:
- `cool_otter.png` — image only (used as-is)
- `cool_otter.txt` — prompt only (art generated from it)
- `cool_otter.png` + `cool_otter.txt` — image is used, prompt rides along as refine context

### 2. Process the inbox (dry-run first)
```bash
python3 -m empire drop                 # dry-run: builds drafts + mockups, pushes cards to .206
python3 -m empire drop --live          # actually creates the Printify drafts (still just DRAFTS)
```
`--live` only creates Printify **drafts** + posts approval cards. Nothing goes to
Etsy until you approve and run `mc-poll`. Add `--no-publish` to skip the .206 push.

To run continuously and auto-process new drops:
```bash
python3 -m empire watch --interval 10          # dry-run loop
python3 -m empire watch --interval 10 --live    # creates drafts as files land
```
Processed drops are moved to `inbox/processed/<timestamp>/`.

### 3. Open the approval UI (reachable from this laptop)
The .206 MC server binds to localhost on .206, so open an SSH tunnel:
```bash
python3 -m empire mc-open               # forwards localhost:3333 → .206, prints the URL
```
Then browse **http://localhost:3333/public/empire-picks/index.html**.
Leave `mc-open` running; Ctrl-C closes the tunnel.

Each card shows the product label (e.g. "Tee · 7 colors", "15oz Mug") and has:
- **✅ APPROVE** / **❌ REJECT**
- **✏️ REFINE** — type an instruction (e.g. `add "Est. 2024" under the art`) to
  tell Printify to change the art/text/accessories. Queued; applied on next poll.

### 4. Apply decisions
```bash
python3 -m empire mc-poll               # dry-run: shows what approve/reject/refine would do
python3 -m empire mc-poll --live        # publishes approved drafts (→ Etsy), applies refines, closes rejects
```
- **approve** → Printify `publish_product` → syncs to Etsy.
- **refine** → regenerates art (from prompt + note) or overlays text, updates the
  Printify draft, rebuilds the mockup, and re-posts the card so you can refine
  again or approve. Refine is non-terminal; tracked in `data/refine_processed.json`.
- **reject** → closes the draft.

## Color note (tie-dye)
The tee bundle ships **black, navy, light blue, red, orange, yellow (Maize),
grey (Athletic Heather)** as variants on one Bella+Canvas 3001 listing.
**Tie-dye is not available** on this blueprint from any Printify provider, so it
cannot be a color variant here — it would need its own tie-dye garment listing.
See `core/bundle.py:TIE_DYE_NOTE`.

## Image backends
Auto-selects: Kie.ai (if `KIEAI_API_KEY`) → OpenRouter (`OPENROUTER_API_KEY`,
currently set, flux-schnell) → OpenAI → ComfyUI → placeholder. Override with
`--backend` or `EMPIRE_IMAGE_BACKEND`.

## .206 details
- SSH alias `floor2` (`~/.ssh/floor2_key`) → 192.168.1.206.
- MC app is pm2 process `mission-control`; approval routes in
  `routes/empire.js`, decisions in `data/empire-decisions.jsonl`.
- Config lives in `.env` (`MC_HOST`, `MC_SSH_KEY`, `MC_PUBLIC_DIR`, `MC_DATA_DIR`).

## Alternative: fully-local gate (no .206)
`python3 -m empire gate --port 3333` runs a self-contained local approval/edit
UI. Not needed for the drop→.206 flow above; kept for offline use.
