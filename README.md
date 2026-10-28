# Aijo Nails Torino — website

One-page website for **Aijo Nails**, a nail salon in Via Monginevro 4, Torino.
Written in Italian, mobile-first, pink pastel with soft 3D ("clay") styling.

## What's on the page

- **Hero** with the logo, "Unghie da sogno a Torino", and buttons to book on WhatsApp or call
- **Servizi**: six service cards with starting prices
- **Listino prezzi**: the full price list in tabs (Mani, Piedi, Ricostruzione, Rimozioni, Ceretta, Pacchetti ceretta)
- **Come prenotare**: three booking steps
- **Instagram** link to @aijonails1
- **Dove siamo**: address with a Google Maps link, phone, WhatsApp, Instagram
- On phones, a floating WhatsApp / Chiama bar appears once you scroll past the top

## Files

```
index.html          all page content (texts, prices, links)
css/style.css       colours, fonts, layout
js/main.js          mobile menu, price tabs, booking bar, animations
img/                logo, favicon, share image (og-image.jpg)
fonts/              Fredoka, Nunito, Dancing Script (self-hosted)
```

It's a plain static site: no build step, no frameworks. Open `index.html` in a browser or upload the folder to any static host (Netlify, GitHub Pages, Cloudflare Pages…).

## Common edits

- **Prices**: in `index.html`, search for the service name (e.g. `Manicure semipermanente`) and change the number in the `<span class="price">` next to it.
- **Phone / WhatsApp**: the number appears as `393382620836` in the WhatsApp links (`wa.me/…`) and `+393382620836` in the `tel:` links; search and replace both forms.
- **Colours**: the palette lives in the `:root` block at the top of `css/style.css`.

## Privacy

The site loads no cookies, analytics or third-party resources: fonts are served from the site itself, and Google Maps opens only when a visitor taps the link.

## Credits

Fonts: Fredoka, Nunito and Dancing Script (SIL Open Font License). Icons: WhatsApp and Instagram glyphs from Simple Icons (CC0), UI icons from Lucide (ISC).
