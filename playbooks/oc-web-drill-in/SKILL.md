---
name: oc-web-drill-in
description: Read a web page without burning tokens — render it budgeted, locate the part you need, then read only that region
tags: [web, browse, scrape, read, tokens, oc, webcapture]
allowed-tools: [oc]
status: draft
---

## Steps

1. oc in: {url: raw}       out: Page
2. oc in: {query: s1/out}  out: Region
3. oc in: {region: s2/out} out: Text

## What this is

Rung 2 of the `/webcapture` ladder. `oc` renders a page once as numbered
regions, then answers follow-up questions from that saved state — `find`,
`read` and `next` never refetch. The saving comes from reading one region
instead of a whole page.

Step by step:

1. `oc open <url>` — fetch and render with a token budget (default 500),
   printing numbered regions and links.
2. `oc find <query>` — locate where a string appears on the page already
   open. When exactly one place matches, it returns the region itself.
3. `oc read <n>` — full text of region `[n]`, up to 2000 tokens.

`oc do <n>` follows link `[n]` (or reads it, if it is text) to drill further;
`oc next` prints the next budget's worth of the same page.

## When NOT to use this

- **localhost** — `oc` refuses it by design (SSRF guard). Use `curl`.
- **Bulk ingestion into a corpus** — use `trafilatura`; this playbook is for
  reading, not harvesting.
- **JS-rendered pages** — `oc` exits 2. Escalate to Playwright (rung 5).

`oc sites` lists the built-in shortcuts (`oc hn top`, `oc reddit sub ClaudeAI`)
which skip step 1's URL entirely.
