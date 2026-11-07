# Raggie external chat widget

A dependency-free, Shadow-DOM-isolated chat widget for embedding on a public
website. Built as a standalone asset (no Next.js), served from the **public
edge** (not the admin backend), one of the layers that keep a widget token away
from every admin API (design target A4,
[ARCHITECTURE §8 and §12](../docs/ARCHITECTURE.md#8-the-widget)).

## Embed

```html
<script src="https://EDGE_HOST/widgets/embed.js?id=WORKSPACE_ID"></script>
```

`embed.js` reads the workspace id from its own query string and derives the API
origin from its own `src`, then mounts the widget into a Shadow root so the host
page's CSS is fully isolated.

## How it stays inside the A4 boundary

1. **Physical surface separation** — shipped as a standalone asset from the
   public edge, never bundled with the admin app.
2. **Audience scope** — calls `POST /api/v1/widget/token` to obtain a
   short-lived `aud=widget` token; that audience is rejected by the admin API.
3. **EXTERNAL-type check** — the token endpoint only issues for `type=EXTERNAL`
   workspaces (others return 404).
4. **Per-workspace CORS** — the requesting `Origin` must be on the workspace's
   allow-list (wildcards rejected); the edge echoes a single explicit origin.

## Configuration

The widget's primary color and display name come from the workspace's
`widget_primary_color` / `name`, returned by the token endpoint — set them in
the admin UI (`PUT /api/v1/admin/workspaces/{id}/widget`).

## Local demo

Open `demo.html` after starting the stack (Caddy serves `embed.js` at
`http://localhost/widgets/embed.js`; the edge's loopback debug port
`http://localhost:8080` works too). Set `WORKSPACE_ID` to an EXTERNAL
workspace and add the demo origin to its CORS allow-list.
