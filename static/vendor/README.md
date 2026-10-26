# Bundled third-party front-end files

Self-hosted so the site works without reaching a CDN (and so visitor browsers do not call third parties).

| Files | Source | Licence |
| --- | --- | --- |
| `bootstrap/bootstrap.min.css` | Bootstrap 5.1.3 (getbootstrap.com) | MIT |
| `html2canvas/html2canvas.min.js` | html2canvas 1.4.1 (html2canvas.hertzen.com), draws the invoice as a picture in the browser | MIT |
| `fontawesome/css/all.min.css`, `fontawesome/webfonts/fa-solid-900.woff2`, `fa-regular-400.woff2` | Font Awesome Free 6.0.0 | Icons CC BY 4.0, fonts SIL OFL 1.1, code MIT |

To upgrade: download the new `dist` files from the same projects over the old ones, run the tests, and look at the pages.
The brand icons font is not bundled (the site uses no brand icons); add `fa-brands-400.woff2` if that changes.
