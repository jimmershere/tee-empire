# Anatomy avoid vocabulary

Curated from `mikhail-bot/stable-diffusion-negative-prompts` and the "Avoid"
clauses scattered through `EvoLinkAI/awesome-gpt-image-2`. Tailored for
**cartoon-mascot t-shirt designs** — not photorealism — so we drop terms that
only matter for photo-style portraits.

The image-gen backends in empire (`nano-banana-2`, `FLUX`, `SDXL`) handle
negatives differently:

- **SDXL/FLUX via ComfyUI** — pass these into the negative CLIPTextEncode node.
- **nano-banana-2 / GPT-Image-2 / cloud APIs** — fold them into the positive
  prompt as an explicit `Avoid: …` clause. Models honour it surprisingly well.

`empire/core/prompt_craft.py` selects the right vocabulary per subject type and
writes the `Avoid:` clause for cloud backends automatically.

## by_subject

### cartoon_mascot
Stylised cartoon characters (skeletons, animals with cartoon proportions, brand
mascots). We want clean linework and correct limb counts, not photoreal anatomy.

```
extra limbs, missing limbs, fused limbs, extra arms, extra legs, missing arms,
missing legs, three legs, six fingers, four-fingered hand on a five-finger character,
mutated hand, fused fingers, malformed face, mirrored face, doubled face,
two heads, conjoined twin, off-model anatomy, broken silhouette, floating limb,
disconnected limb, cluttered background, busy negative space, extra characters,
duplicate of the subject, watermark, signature, artist mark, caption, logo,
QR code, jpeg artifact, gradient noise
```

### humanoid
Detailed human or near-human figure (not used for default earl_biggers but here
when needed).

```
extra fingers, six fingers, four fingers on a hand intended to be five-fingered,
fused fingers, mutated hand, poorly drawn hand, twisted finger, broken finger,
missing thumb, extra elbow, extra knee, three legs, missing limb, floating limb,
disconnected limb, malformed limb, bad anatomy, gross proportions, long neck,
mirrored face, doubled face, cloned face, two heads, distorted face, asymmetric eyes,
deformed mouth, watermark, signature, caption, logo, jpeg artifact
```

### animal
Animals — quadrupeds, birds, sea life. The model's most-frequent mistake here
is leg count and eye placement.

```
wrong number of legs, three legs, five legs, missing leg, extra leg,
extra tail, two tails, missing tail, missing ear, three ears, fused ears,
extra eye, three eyes, missing eye, mirrored eyes, asymmetric face,
deformed paw, malformed snout, broken silhouette, off-model anatomy,
watermark, signature, caption, logo, jpeg artifact
```

### typography_only
Pure text/logo designs. The risk is the model sneaking in a face or hand.

```
no people, no faces, no hands, no body parts, no animals, no characters,
no random objects, no clutter in negative space, watermark, signature,
caption, logo, QR code, jpeg artifact, gradient noise, garbled text,
duplicated text, misspelled headline, extra characters in the text
```

### universal
Always append regardless of subject. These guard against marketplace-rejecting
artefacts.

```
watermark, signature, artist mark, copyright mark, brand logo,
caption text outside the headline, QR code, stock-photo overlay,
jpeg compression artifacts, ringing, blurry edges
```
