## Development

When starting the dev server, use background mode:

```
astro dev --background
```

Manage the background server with `astro dev stop`, `astro dev status`, and `astro dev logs`.

The dev server runs on port 4323 (4321 = docsite/website, 4322 = docsite/website-vision).

## Content rules

- The brand wordmark is always lowercase: `yoyopod`, rendered with the
  bounce-p (the `p` drops 0.07em — use the `Wordmark.astro` component; rules
  in `docs/brand/README.md`).
- Design tokens live in `src/styles/global.css`: navy ground, cream voice,
  cyan accent (actions/hovers only), four pastel finish chips.
- Page copy comes from `docs/product/LANDING_PAGE_POSITIONING.md`. Do not market
  yoyopod as "AI for kids", "a communication platform", "a smart wearable", or
  "an educational device" (see the blunt positioning note in that doc).
- The age range is 7–14.
- Every device image must carry a caption noting it shows the V2 design study,
  not shipped hardware (`docs/product/README.md`).

## Documentation

Full documentation: https://docs.astro.build

- [Adding pages, dynamic routes, or middleware](https://docs.astro.build/en/guides/routing/)
- [Working with Astro components](https://docs.astro.build/en/basics/astro-components/)
- [Adding styles](https://docs.astro.build/en/guides/styling/)
- [Images](https://docs.astro.build/en/guides/images/)
