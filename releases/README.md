# Releases

Release notes for the two images that make up **API Discovery for NGINX**.

The dashboard and the agent are versioned and published together — always run them on the **same version tag**.

| Version | Date | Highlights |
|---------|------|------------|
| **1.2.1** | 2026-08-13 | Fixes for the dashboard language switcher — help icons, re-render, 81 unkeyed strings. No behavioural changes. |
| 1.2.0 | 2026-08-12 | Dashboard interface is now **English**, with an EN/KO switcher. No behavioural changes. |
| 1.1.0 | 2026-08-11 | Dashboard image is **10× smaller to pull** (2.8 GB → 288 MB). No functional changes. |
| 1.0.0 | 2026-07-08 | Initial release. |

## Per-image notes

- [`api-discovery-nginx`](api-discovery-nginx/) — collector server + web dashboard
- [`api-discovery-agent`](api-discovery-agent/) — NGINX log-collecting agent

## Tagging policy

- `latest` — the newest stable release. Always points at the same digest as the newest version tag.
- `X.Y.Z` — pinned version. **Use this in production**, not `latest`.

Images are published for `linux/amd64`.
