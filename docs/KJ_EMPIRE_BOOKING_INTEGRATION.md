# KJ Empire — Booking Infrastructure Integration Guide

> **Status: 🟢 LIVE & READY** — as of 2026-06-24
> **System:** KJEmpireCalz (self-hosted Cal.com)
> **Tagline:** *One booking infrastructure. Every empire product. Forever free.*

This is the canonical reference for connecting **any** King James Empire app to the empire's shared booking plumbing. If your product needs scheduling, calendars, availability, time zones, or booking links — **you do not build it. You plug into KJEmpireCalz.**

---

## 1. TL;DR

KJEmpireCalz is a self-hosted Cal.com instance that serves as the single booking layer for the whole empire. Each product registers as a **Team**, embeds one **widget**, and receives **webhook events** when bookings happen. The product owns everything downstream (its own database, customer records, and post-booking logic). KJEmpireCalz owns scheduling itself.

- **Booking host:** https://book.empirecalz.com
- **Docs site:** https://empirecalz.com
- **Integration kit (drop-in templates):** `/opt/empirecal/integration-kit/` on the RackNerd VPS
- **Recurring cost:** $0 — it runs on existing empire infrastructure

---

## 2. Who owns what

| KJEmpireCalz owns | Your product owns |
|---|---|
| Scheduling, availability, time zones | Business logic |
| Calendar sync, booking pages | Customer records / CRM |
| Booking-time reminders & confirmation emails (via Resend) | Post-booking workflows |
| Video-conferencing links | Billing (via KJEmpirePayz) |
| The booking widget & event types | Your own database writes |

**Rule of thumb:** if it's about *when* a meeting happens, it's EmpCalz. If it's about *what your business does* with that meeting, it's your product.

---

## 3. The integration contract (5 steps)

1. **Register a Team** inside KJEmpireCalz using your product's slug (e.g. `iasy`, `reviewbombz`, `voicedropz`, `kjwidgetz`).
2. **Embed the booking widget** on your product's frontend — one snippet (`embed-snippet.html` from the kit), with brand-override slots so it matches your product.
3. **Register a webhook URL** pointing at your product's backend.
4. **Receive the four standard events** and act on them in your handler.
5. **Own your downstream:** write to your Supabase, fire your own product-specific emails if needed, etc.

---

## 4. The four standard webhook events

Every integration receives the same event contract:

- `BOOKING_CREATED`
- `BOOKING_RESCHEDULED`
- `BOOKING_CANCELLED`
- `MEETING_ENDED`

Each webhook payload is **HMAC-signed**. Your handler **must** verify the `X-Cal-Signature-256` header against your webhook's signing secret before trusting the payload. The kit's handlers do this for you — don't strip it out.

---

## 5. The integration kit

Everything you need is at `/opt/empirecal/integration-kit/`. Copy what you need:

| File | Purpose |
|---|---|
| `embed-snippet.html` | Drop-in booking widget with brand-override slots |
| `webhook-handler.py` | FastAPI handler (HMAC-verified, 4-event switch) |
| `webhook-handler.ts` | Next.js App Router handler (same contract) |
| `bookings-schema.sql` | Supabase/Postgres `bookings` table migration (template) |
| `confirmation-email.html` | Resend-ready, KJ-branded |
| `reminder-24hr-email.html` | Resend-ready, KJ-branded |
| `cancellation-email.html` | Resend-ready, KJ-branded |
| `README.md` | 10-minute integration walkthrough |

---

## 6. Email

KJEmpireCalz **already sends** booking confirmations, reschedules, cancellations, and reminders itself, through **Resend** on the verified `empirecalz.com` domain (from `bookings@empirecalz.com`). You generally don't need to send booking emails yourself. If you want *product-branded* emails on top of that, the kit's three templates are there to use with your own Resend sends from your webhook handler.

---

## 7. Payments — via KJEmpirePayz (do NOT wire Stripe)

Payments are handled empire-wide by **KJEmpirePayz** (forthcoming). The integration kit's payment hooks are **deliberate stubs** (`handlePaymentViaKJEmpirePayz`) that swap in for the real client when KJEmpirePayz ships.

> ⚠️ **Do not integrate Stripe directly in any product.** All payment plumbing routes through KJEmpirePayz so the empire has one Stripe surface, not many.

---

## 8. Brand (so embeds match the empire)

KJ dark-cyberpunk palette — use these in your embed's brand-override slots:

| Token | Hex |
|---|---|
| Base (navy/near-black) | `#0A0E1A` |
| Panels | `#121A2E` |
| Primary accent (cyan) | `#3BE0D0` |
| Secondary (gold) | `#E9B949` |
| Crown / highlight | `#FBE3A1` |

Mark: a gold crown. Headings lean techy/mono.

---

## 9. How a product gets onboarded — and how you know it's ready

**You already know — because of this doc and the Brain announcement.** Readiness is broadcast two ways:

1. **The KJ Brain.** A standing announcement memory is posted (tags: `kjempirecalz`, `announcement`, `integration`, `all_products`, `ready`). Any product's Claude/SC session that searches Brain for booking, scheduling, or calendar work will surface it. This is the empire-native "all-call."
2. **This document.** It's the canonical reference — link it from each product's `CLAUDE.md` / `KJ_RULEZ.md` under technical standards, so every future build session points here.

**To onboard a specific product (the SC checklist):**

- [ ] Confirm the product genuinely needs booking (if not, skip — don't add a Team for nothing).
- [ ] Register the product's Team in KJEmpireCalz with its slug.
- [ ] Copy `embed-snippet.html` into the product frontend; fill the team/event/brand slots.
- [ ] Stand up a webhook endpoint from `webhook-handler.py` or `.ts`; set its signing secret.
- [ ] Apply `bookings-schema.sql` to the product's own Supabase.
- [ ] Wire the four events to the product's downstream logic (DB write, notifications).
- [ ] Leave payments on the KJEmpirePayz stub — do not add Stripe.
- [ ] Test one end-to-end booking before going live.

**First in line:** IASY Atelier — gated on **IASY Prompt 20** completing.

---

## 10. Config & secrets (reference only)

Secrets live in the **Brain vault**, never in code:

- `empire/KJEMPIRECALZ_R2_ACCESS_KEY_ID` / `..._SECRET_ACCESS_KEY` — dedicated backup bucket creds
- `shared/BACKUP_ENCRYPTION_KEY` — master backup decryption key (escrowed offline)
- `iasy/RESEND_API_KEY` — shared Resend key (email)
- `empire/kjempirecalz_*` — Cal.com core secrets (DB password, NextAuth, encryption key)

Backups: nightly encrypted `pg_dump` + config archive to `R2:empire-backups/empirecal/`.

---

*Maintained by the KJEmpireCalz Strategic Commander. KJEmpireCalz sits **above** all products — empire-level infrastructure, internal-first, public-optional.*
