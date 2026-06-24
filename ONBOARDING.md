# Customer Onboarding — new brand → live merch + ads

This is the repeatable process for bringing a **new customer/brand** into the
pipeline (tee-empire designs + Printify/storefront, clemtock ads). Madd Hatchery
is the reference build. A brand goes from a 10-minute intake to a scaffolded
brand, a clemtock ad theme, and a first drop of designs.

---

## 1. Intake prompt (run this with the customer)

Paste this to the customer (or to an LLM acting as intake agent). Capture the
answers into `intake.json` (schema in §2).

> **Welcome! Let's set up your brand. A few quick questions:**
> 1. **Brand name** and a one-line description of what you sell?
> 2. **Where are you based?** (town/region — we lean on the local angle)
> 3. **Website / domain** (or "none yet") and your **social handles** (TikTok, IG, FB…)?
> 4. **What products?** (jams, tees, mugs, stickers, bottles, eggs, …)
> 5. **Brand colors** — 2–4 you love (names or hex). Got a **logo**? (send the file)
> 6. **A mascot or character?** Describe them, or send art (we keep them consistent across designs).
> 7. **Voice in 3 words** (e.g. "down-home, witty, sassy") and who's your **audience**?
> 8. **5–10 design ideas / taglines** you'd want on merch?
> 9. **Print-on-demand**: do you have a Printify/Etsy shop, or sell direct (Stripe)?

Keep it friendly and short. Anything missing, use a sensible default and confirm later.

---

## 2. intake.json schema

```json
{
  "slug": "madd_hatchery",
  "name": "Madd Hatchery",
  "tagline": "small-batch jams · farm-fresh · merch",
  "location": "Hubert, NC",
  "site_url": "https://maddhatchery.com",
  "socials": { "tiktok": "jimmerk4", "instagram": "jimmers_here", "facebook": "..." },
  "voice": "wholesome hippy-country farm humor, witty and a little sassy",
  "palette": { "primary": "#119aa0", "secondary": "#7a3f9d", "accent": "#e0922f", "cream": "#f6eedb" },
  "logo": "path/to/logo.png",
  "mascot": { "name": "Trish", "ref": "path/to/character.png", "desc": "curly red hair, glasses, headset, tie-dye" },
  "products": ["jams", "tees", "mugs", "stickers", "bottles"],
  "audiences": { "farm-girls": "local, market-day, down-home" },
  "lanes": { "house": ["Need Some Eggs?", "All Jammed Up"], "novelty": ["Disco Possum", "Porch Goblin"] },
  "commerce": { "printify_shop_id": "", "storefront_api": "https://maddhatchery.com", "qr_target": "https://maddhatchery.com" }
}
```

---

## 3. Process (per customer)

1. **Scaffold** — `python scripts/onboard_brand.py intake.json`
   → writes `brands/<slug>/brand.yaml` + `brands/<slug>/lanes/*.json`,
   the clemtock theme `../clemtock/themes/<slug>.json`, and a
   `brands/<slug>/fixtures/` for the logo + mascot reference.
2. **Drop in art** — copy the customer's `logo.png` and `character.png` into
   `brands/<slug>/fixtures/` (mascot ref powers img2img on brand-character lanes).
3. **Generate** — `python -m empire plan --brand <slug> --per-lane 5`
   then `python -m empire design --brand <slug> --product-type shirt --live`
   (mugs/stickers/bottles: re-run with `--product-type mug|sticker|bottle`).
4. **Review** — `python -m empire mc-publish --brand <slug>` → approve on floor2.
5. **Publish** — on approval: Printify drafts (`empire list --platform printify --live`)
   and/or the storefront (`empire publish-site --brand <slug> --live`).
6. **QR merch** — logo sticker/mug/bottle with a bottom-left QR → the customer's
   `qr_target` (see the Madd Hatchery merch build for the recipe).
7. **Ads** — clemtock picks up the new theme automatically (`"theme": "<slug>"`):
   `python -m clemtock assets`/`export` to render, then `publish` to socials.

---

## 4. Defaults & fairness

- **Pricing** (fair to the customer, still profitable): sticker $4–6, mug $14–18,
  bottle $24–28, tee $25–30. Tune to the customer's market.
- **QR**: high error-correction, bottom-left, on a small white chip so it scans.
- Keep mascots consistent via `fixtures/character.png` + the img2img path.
