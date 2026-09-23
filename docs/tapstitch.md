# Tapstitch for apparel — what is and isn't possible

Research answer for "connect it to tapstitch.com for shirts, hoodies, apparel".
Written 2026-09-11.

## The finding

**Tapstitch has no public developer API.** It cannot be wired into the pipeline
the way Printify is.

What Tapstitch documents is the *opposite* direction: you connect **your
storefront** to Tapstitch, and Tapstitch pushes products into it. Their
"REST API key" in the WooCommerce help article is a **WooCommerce** key you paste
into Tapstitch's dashboard — not a Tapstitch key you call.

Searched: tapstitch.com help centre, their print-on-demand landing page, and open
web for developer docs. No base URL, no endpoints, no auth scheme, no developer
portal. Sources at the bottom.

| | Printify | Tapstitch |
|---|---|---|
| Public REST API | yes — `https://api.printify.com/v1` | **none found** |
| Create product from code | yes | no |
| Upload art from code | yes | no |
| Fetch mockups from code | yes | no |
| Storefront connectors | Etsy, Shopify, … | Shopify, TikTok, **Etsy**, Wix, Squarespace, WooCommerce, Shoplazza, BigCommerce |

So the split the request assumes — apparel via Tapstitch, hard goods via Printify
— is **operationally lopsided**, not symmetric. Hard goods stay fully automated;
apparel would gain a permanent manual step.

## Three honest options

**A. Keep apparel on Printify.** Zero new work; `publish_merch_draft.py` and the
existing tee pipeline already cover it. Choose this unless Tapstitch's blanks,
print quality or margins are specifically better for what you're selling.

**B. Tapstitch as a manual lane, tee-empire prepares the handoff.** The pipeline
stops at print-ready art plus listing copy; you upload to the Tapstitch dashboard
and let *Tapstitch's own Etsy connector* create the listing. tee-empire never
touches Tapstitch. This is the only shape that actually works today.

**C. Ask Tapstitch for API access.** They may have a partner/private API. Worth
one email before building around option B. Until there's a written contract, do
not build a speculative client — an invented integration is worse than none
(fleet rule 6).

**Recommendation: A for now, B if you commit to Tapstitch blanks.** Revisit on C.

## If you go with B

The handoff bundle per design is: the print file at the blueprint's spec, a
mockup for reference, and the listing copy. Note that under option B the Etsy
listing is created by *Tapstitch*, not by tee-empire's `core/etsy.py` — two
systems writing to one Etsy shop is a real collision risk. Decide which one owns
apparel listings **before** the first upload, not after.

Open question this raises, in the style of the venture's other unknowns:

| # | Question |
|---|---|
| TE-9 | If apparel moves to Tapstitch, who owns the Etsy listing — Tapstitch's connector or `core/etsy.py`? They must not both. |

## Operational note

Tapstitch documents that requests may be blocked by Cloudflare and asks merchants
to whitelist `47.254.82.144`. Relevant only if the AU2 / Earl Biggers storefront
ever sits behind Cloudflare.

## Sources

- [Tapstitch — integrate my WooCommerce store](https://www.tapstitch.com/help-center/faq/detail/integrate-my-Woocommerce-store)
- [Tapstitch — print on demand](https://www.tapstitch.com/print-on-demand)
- [Tapstitch: Print on Demand (Shopify app listing)](https://apps.shopify.com/odmpod-dropshipping)
- [Printify API reference](https://developers.printify.com/) — for contrast
