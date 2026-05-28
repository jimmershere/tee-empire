---
name: image_craft
description: Anti-hallucination + prompt-craft skill for empire's image generation. Distilled from three GitHub resources (EvoLinkAI/awesome-gpt-image-2, wuyoscar/GPT-Image2-Skill, mikhail-bot/stable-diffusion-negative-prompts) and tuned for cartoon-mascot t-shirt designs on nano-banana-2 / FLUX / SDXL.
metadata:
  source: https://github.com/jimmershere/exec_dashbd
  vendored_skills:
    - EvoLinkAI/awesome-gpt-image-2-API-and-Prompts
    - wuyoscar/GPT-Image2-Skill
    - mikhail-bot/stable-diffusion-negative-prompts
---

# Image craft skill

Use this skill any time empire is composing a t-shirt design prompt that includes
a character, mascot, hand, face, animal, or any anatomy. It produces prompts
that suppress the classic generative-image failure modes (extra fingers, fused
limbs, mirrored faces, mutated proportions, accidental watermarks).

## When to use

| situation | apply |
|---|---|
| any prompt with a cartoon mascot (skeleton, animal, character) | `enhance_design_prompt(prompt, subject="cartoon_mascot")` |
| any prompt with a humanoid figure | `enhance_design_prompt(prompt, subject="humanoid")` |
| any prompt with an animal | `enhance_design_prompt(prompt, subject="animal")` |
| pure typography, no character | `enhance_design_prompt(prompt, subject="typography_only")` |
| complex multi-system shot (product render, hero pose with environment) | use the JSON-config schema in `craft.md` |

## The three layers

1. **Forbid (Avoid clauses)** — codified negative vocabulary appended to every prompt.
   See `anatomy_avoid.md`. Stops six-fingered hands, fused limbs, mirrored faces, accidental watermarks, etc.

2. **Scaffold (prompt structure)** — every prompt follows the same shape:
   *canvas → subject → style → composition → avoids*. See `craft.md` rule 1.

3. **Show good** — gallery-style positive descriptors that name specifically what
   you want, leaving no room for the model to improvise. See `craft.md` rule 3.

## Python entry point

```python
from empire.core.prompt_craft import enhance_design_prompt

raw = "Print-ready t-shirt graphic on a black background. Bold cartoon-line skeleton crouched..."
final = enhance_design_prompt(raw, subject="cartoon_mascot", headline="Running on Spite")
# final has: original prompt + Avoid clause + style anchors + canvas-first ordering verified
```

`empire/core/concepts.py::_voiced_design_prompt` calls this automatically.

## Quick rules (the only ones that matter day-to-day)

1. **Headline goes in quotes** — `The headline reads exactly: "Running on Spite"`.
2. **Canvas before subject** — start with "Print-ready t-shirt graphic on a {color} background" before describing the mascot.
3. **One subject per design** — say "single subject, no duplicates" or the model invents extras.
4. **Avoid clause is mandatory** for any character/mascot prompt.
5. **Name the style narrowly** — "vintage screenprint, 2-color, hand-drawn line art" beats "stylized".
6. **For complex shots, use the JSON-config schema** in `craft.md` — labelled subsystems beat prose.
