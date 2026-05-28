# Prompt craft — empire-specific distillation

Distilled from `wuyoscar/GPT-Image2-Skill/skills/gpt-image/references/craft.md`
(MIT). Keeping only what's relevant for t-shirt designs on `nano-banana-2`,
`FLUX-schnell`, and `SDXL`.

## 1. Canonical prompt shape

```
{canvas} {subject} {style} {composition} {headline_block} {avoid_clause}
```

Each section is **one line**. Order matters — the model allocates description
budget in the order it reads.

- **canvas**: "Print-ready t-shirt graphic on a {color} background."
- **subject**: one-line description of the focal illustration (or "minimal typography").
- **style**: "vintage screenprint, 2-color, hand-drawn cartoon line art, subtle distress."
- **composition**: "centered chest-print, generous negative space, single subject."
- **headline_block**: `The headline reads exactly: "Running on Spite" in tall bold uppercase sans-serif lettering.`
- **avoid_clause**: `Avoid: extra limbs, fused fingers, mirrored face, watermark, …`

## 2. Headline = literal text in quotes

GPT-Image-2 / nano-banana-2 render typography accurately ONLY when the exact
copy is in quotes:

- weak: *Add the brand name and slogan.*
- strong: `The headline reads exactly: "Do It Tired" in bold sans-serif.`

Always use the verbatim title from the concept; never let the model paraphrase.

## 3. Style anchors are bounded, not vibes

Bad: "stylish, modern, beautiful, cinematic" → the model picks any of 1000 looks.

Good: "vintage screenprint, 2-color, ink-bleed texture, hand-drawn line art,
1960s comic-book aesthetic" → narrow band.

Always pick anchors from the same era/medium/palette. Mixing "vintage
screenprint" + "ultra-cinematic 8K render" confuses the model.

## 4. Composition primitives

Use one of these structural anchors when describing layout:

- "centered chest-print composition"
- "headline above the illustration, illustration tucked below"
- "rule-of-thirds composition with the mascot in the lower-right"
- "2x2 grid layout"
- "fully bleed-to-edge artwork"

## 5. Single subject discipline

Add `single subject, no duplicates, no extra characters` whenever the prompt
includes a character. nano-banana-2 occasionally invents a sidekick if you
mention any plural noun in the description.

## 6. Avoid clause is mandatory

For any prompt with a mascot/character, append the Avoid clause built from
`anatomy_avoid.md`. Cloud backends (nano-banana-2, GPT-Image-2) honour
in-prompt `Avoid:` instructions; ComfyUI workflows route these into the
negative CLIPTextEncode node automatically.

## 7. JSON-config schema (for complex shots)

When a design has multiple interacting subsystems (mascot + props + background
scene + multiple text blocks), use the JSON-config pattern instead of prose.
Models follow structured schemas more reliably than 600-char paragraphs.

```text
/* TEE_DESIGN_CONFIG: Running on Spite
   VERSION: 1.0
   AESTHETIC: Vintage screenprint cartoon */
{
  "CANVAS": {"aspect_ratio": "1:1", "background_color": "#000000"},
  "STYLE": {
    "medium": "vintage screenprint",
    "palette": ["#FFFFFF", "#C13030 (single accent)"],
    "linework": "hand-drawn cartoon, bold outlines",
    "texture": "subtle ink-bleed distress"
  },
  "SUBJECT": {
    "type": "single cartoon mascot",
    "description": "exhausted skeleton crouched lacing running shoes",
    "details": ["sweatband on skull", "steam billowing from top of skull", "red sneakers"]
  },
  "HEADLINE": {
    "text": "Running on Spite",
    "position": "above the subject",
    "typography": "tall bold uppercase sans-serif, white ink"
  },
  "COMPOSITION": "centered chest-print, single subject, generous negative space",
  "AVOID": [
    "extra limbs", "missing limbs", "fused fingers", "mirrored face",
    "two heads", "duplicate subject", "watermark", "caption text"
  ]
}
```

Use this for: any prompt that has 5+ visual systems, when text rendering must
be exact, or when previous prose-style prompts produced inconsistent results.

## 8. Edit endpoint preservation

When using `gpt-image-2` edit mode with a reference image (not the default empire
flow, but available for "fix this design" workflows): always say *"Preserve the
existing typography, palette, and composition. Only modify X."*

## 9. Iteration loop

1. Generate 4 variants with empire's parallel dispatcher.
2. Claude vision judge picks best.
3. If best variant fails anatomy check (visible extra limbs, broken text, etc.),
   tighten the Avoid clause and re-run.
4. Three rounds max before pivoting to manual prompt tuning.

## 10. What this skill does NOT cover

- Reference-image anchoring across multiple gens (identity locking) — not used
  in empire since each variant is fresh.
- Multi-turn editing dialogue — empire is one-shot per variant.
- Chinese typography — not in scope for English-only Etsy listings.
- Photo-style anatomy — empire uses cartoon mascots; the photoreal avoid
  vocabulary in `anatomy_avoid.md` is included for completeness only.
