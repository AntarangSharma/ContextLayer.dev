# Hype Relaunch Plan — Landing + Narrative

**Premise:** the current page is technically correct but emotionally flat. It reads
like a README in HTML form. We need to convert it into a *product launch* — a page
that makes a senior dev say "wait, what is this?" within 3 seconds and reach for
GitHub within 30.

## Honest audit (what's wrong right now)

| Symptom | Root cause | Cost |
|---|---|---|
| 922 lines, 9 sections, 4 screens of scroll | Trying to explain everything | Dilutes the punch |
| Hero leads with a problem ("forgets your rules") but the resolution is generic | "ContextLayer turns your repo's history into structured knowledge atoms…" reads like documentation, not a promise | Low conversion |
| First number visitors see is **\$1.50/repo** | Cost-leading framing on a free tool | Repels the OSS / curious-dev segment |
| Zero social proof anywhere | Solo project, no traction yet | Reads as "guy's side project" |
| All proof is static (code blocks, fake JSON) | No live demo, no telemetry, no GIF | Easy to scroll past |
| Roadmap takes ~150 lines | Detail-heavy on a homepage | Distracts from the wedge |
| No founder voice / personal stake | Marketing-y third-person | Forgettable |
| "BYOK · ANTHROPIC_API_KEY" / "~\$1.50 / repo" badges in hero trust row | Old framing pre-tier-router | Outdated + boring |

## What hype actually looks like in dev tools (2024–2026 patterns)

Studied the launches that *worked* in the last 18 months — Cursor, v0, Perplexity,
Linear, Resend, Trigger.dev, Mintlify, Modal. The common ingredients:

1. **A single visceral claim with a number** above the fold. "37% faster than X."
   "Indexed 500 repos in 6 minutes." "$0 forever." Specifics > adjectives.
2. **A live demo, not a screenshot.** A real input box that returns a real result.
   Even if it's just one canned query, it must *move*.
3. **Asymmetric proof.** A benchmark, a chart, or a one-line comparison that's
   impossible to argue with.
4. **A founder line, in first person.** "I built this because…" — humans buy from
   humans.
5. **Tension–resolution motion.** An animated terminal that types the *bad*
   answer, then types the *good* answer. Static side-by-side ≪ animated.
6. **Aliveness signals.** A live counter ("47 atoms surfaced this hour"), a
   pulse dot on a real metric, a deploy/commit timestamp.
7. **A single quotable line.** "Stop teaching your AI your codebase. Index it once."
8. **Ruthless pricing clarity.** "Free. Forever. Bring your own key if you want
   the premium tier."
9. **The killer demo loop.** 30 seconds of GIF/Lottie/animated SVG showing the
   *exact* moment the AI cites a real PR. That's the screenshot people share.

## The new narrative (one paragraph)

> Every Claude session, your AI rewrites the same rules your team already
> wrote down. ContextLayer reads your git history once, compresses every
> convention, deprecation, and anti-pattern into a local SQLite file, and
> serves it to Claude over MCP — with PR citations. Free forever. No login.
> No SaaS. Works offline.

Five sentences. That's the page.

## The new shape (target: ~450 lines, half the current)

```
[1] Hero               — punchy claim + live query input box + GitHub star CTA
[2] Animated demo      — typed terminal: bad answer → good answer (5s loop)
[3] One-stat proof     — "67 atoms · 8 rules · 23 PR citations" from the real demo DB
[4] How it works       — three glyphs: index → query → cite. 30 seconds to read.
[5] Tier table         — Free / Hybrid / Premium, with $0 in big numbers
[6] Killer feature card — context_validate with one real example (current good content)
[7] Quick start        — three lines of code. That's it.
[8] Founder note       — one paragraph, first person, signed
[9] Footer             — GitHub, USER-MANUAL, PyPI, X/Twitter
```

Cuts: full pipeline section (move to /how), giant features grid (consolidate to
4 chips), roadmap (move to /roadmap), waitlist (combine with footer).

## Hype-building moves I'll add

### A. **Live query box** (the single biggest lift)
A real `<input>` above the fold pre-filled with the demo Q1. On click, it hits
a tiny Vercel Edge function that proxies to a hosted MCP query endpoint with
the demo DB, and renders the actual returned atoms with citations. **This is the
hero proof point** — and it's possible because the query path is now keyless.

Implementation: serverless function `api/query.ts` (Vercel Edge), 50 lines.
Hosts the demo DB read-only. Rate-limited via Upstash or a simple in-memory
token bucket.

### B. **Animated terminal** (above the fold, autoplay)
SVG-driven or `typewriter.js`-style. Two columns:
- Left: "Without ContextLayer" — claude types a wrong, threading-using answer.
- Right: "With ContextLayer" — same prompt, but the answer cites PR #421 and
  uses async-first.

Loops every 8 seconds. Static fallback for prefers-reduced-motion.

### C. **"Live atoms" counter strip**
A row right under the hero: "67 atoms · 8 rules · 23 PR citations · 7 topics —
indexed from the demo repo in 47 seconds." Numbers are real, pulled at build
time from the live demo DB. One pulse dot.

### D. **Asymmetric stat card**
A single card: "When Claude is given ContextLayer's atoms, it cites a relevant
PR in **94% of test queries**." With a small bar chart. Need to actually
generate this number from a test set — small lift, big credibility.

### E. **Founder note** (50–80 words, signed)
First person. The "why I built this" paragraph. Photo or initial avatar
optional but raises trust 2x in user studies.

### F. **GitHub social proof bar**
Above-fold strip: GitHub stars badge (live shields.io), commit count, last
commit timestamp. Real, automated, free.

### G. **Three-glyph "how it works"**
Replaces the Haiku/Sonnet/Opus pipeline section. Just three icons:
- 🌳 `contextlayer index .` — reads your git history once
- 🔎 `context_query "…"` — Claude queries via MCP
- 🎯 Answer comes back with PR citations

One sentence under each. 30 seconds to skim.

### H. **Tier pricing table** with $0 in giant numbers
Three cards: Free / Hybrid / Premium. The Free card is bigger and labeled
"Forever." The Hybrid card says "BYOK · ~\$1.50 to index." Premium card
says "Coming soon — hosted team tier."

### I. **Sharper hero line**
Current: "Your AI agent forgets your team's rules. Every. Single. Session."
Already good. Replace the soft sub-line with something punchier:

> **Old:** "ContextLayer turns your repo's history into structured knowledge
> atoms and serves them to Claude Code via MCP — with citations."
> **New:** "Read your git history once. Stop watching Claude reinvent your
> conventions. Free, local, MCP-native — `pip install contextlayer-dev`."

### J. **Sticky bottom CTA bar** (mobile + desktop)
Single thin bar: "★ Star on GitHub · 📖 Read the manual · ⚡ Try in 30s"
that hides on scroll-up, shows on scroll-down past the fold.

## Things I will NOT do (and why)

- **Add fake testimonials.** No social proof beats the no-social-proof we have;
  inventing it would be fatal if caught.
- **Promise features that aren't shipped.** Roadmap moves to `/roadmap`, not the
  homepage hero.
- **Add a video.** Lottie/animated SVG is lighter and feels native; a video
  player feels marketing-heavy on a dev tool.
- **Use stock illustrations.** Code blocks and terminal output only.
- **Charge for the OSS path.** The Free tier stays free forever. That's the
  story.

## Concrete deliverables

1. `landing/index.html` — rewritten, ~450 lines, all hype moves A–J above
2. `landing/api/query.ts` — Vercel Edge function for the live query box
3. `landing/api/stats.ts` — Vercel Edge function returning the live counters
   (atoms / rules / topics) from a hosted read-only copy of the demo DB
4. `landing/assets/demo-loop.svg` — animated terminal (static SVG with SMIL or
   CSS keyframes; no JS needed)
5. `landing/styles.css` (optional, if Tailwind utility soup gets too dense)
6. `landing/roadmap.html` — moved-out roadmap page
7. New twitter/og card image (`landing/og.png`) with the punchy hero line

## Build order

1. **Plan + copy first** — write the final hero line, founder note, tier table
   copy, asymmetric stat copy. Lock the words before any HTML moves.
2. **Backend first** — ship `api/query.ts` and `api/stats.ts` as Vercel Edge
   functions; verify they return real data from the demo DB.
3. **HTML rewrite** — collapse the current 9-section layout to 9 tighter sections,
   replace static elements with the new motion + live demo.
4. **Animation pass** — typed terminal loop, pulse dots, hover micro-interactions.
5. **Performance pass** — Lighthouse to 95+. Inline critical CSS, lazy-load
   non-critical sections.
6. **OG image + meta** — single PNG, generated once.
7. **Push, verify auto-deploy.**

## Open questions for the user (need answers before I start the rewrite)

1. **Voice:** are you OK with a *first-person* founder note ("I built this
   because…")? If yes, what's your one-line story for why?
2. **Live demo:** are you OK with me deploying a hosted read-only copy of the
   demo DB to a Vercel KV/blob store so the live query box works?
3. **Stat claim ("94% citation rate" or similar):** do you want me to actually
   run a small benchmark to generate a *real* number we can publish, or skip
   asymmetric proof for v1?
4. **Pricing copy:** "Free forever" for the OSS query/free-tier path. OK to
   make that explicit on the homepage?
5. **Social handles:** what handle should I put in the footer (X, LinkedIn,
   email)?

Once those five are answered, I can ship the rewrite in one pass.
