Local browser dependencies (no CDN or build step).

- Marked 18.1.1: npm marked, lib/marked.umd.js; MIT license in marked-LICENSE.
- DOMPurify 3.4.17: npm dompurify, dist/purify.min.js; dual Apache-2.0/MPL-2.0 license in DOMPurify-LICENSE and DOMPurify-LICENSE-MPL.

Both artifacts are copied unmodified from the pinned npm packages. Raw HTML is escaped before sanitization; images are replaced by their descriptions and only HTTP(S)/mailto links remain clickable.
