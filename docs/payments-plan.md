# Payments: the plan

**Plan only, 22 Nov 2026. Nothing is decided and nothing is built.** It turns the owner's ideas in
`docs/phase2-build-plan.md` ("Beyond R3") into options, a recommendation for each, a build plan,
the questions for the CA (section 9) and for the owner (section 10). D1 to D10 bind everything
here. Nothing here is legal or tax advice: every such point is "to confirm with the CA" (or the
lawyer). Fees and rules were looked up on 22 Nov 2026; sources are numbered [1], [2] and so on at
the end.

---

## 1. Summary and recommendation

**The owner's idea:** the family pays the mobed's price plus a small service fee that is always
shown (about 10%, capped near ₹50). A payment company (a "gateway") splits the money at once: the
full price to the mobed's or agyari's own bank account, the fee to ours. We never hold the money.
"Paid" becomes automatic, with a ledger and reports.

**The key finding.** RBI's rules for payment companies (15 Sep 2025) let a gateway pay a "third
party", such as a mobed's linked account under Razorpay Route, only for a business with a turnover
above ₹40 lakh a year, and only if that third party is the one serving the customer [1]. Razorpay
applies this to Route: above ₹40 lakh in FY26 or FY25, and Route was switched off on 1 Jan 2026
for those who did not qualify [2]. We are new and small, so **Route, and very likely Cashfree's
Easy Split, are closed to us for now** (to confirm with both in writing).

**So the recommendation is the other way round:**
- **Each agyari is its own merchant** with the gateway. It signs up and does its own KYC; the money
  lands in its own bank account. Our app creates the payment on the agyari's account through the
  gateway's partner or platform programme, and is told when it is paid [7][8][13].
- **Our fee** comes through the same programme: as a platform fee taken from each payment, or as a
  partner commission the gateway pays us. Both exist [7][8]; which is allowed for small agyaries
  under RBI's rules is to confirm with the gateway.
- **Start with Razorpay, and apply to Cashfree at the same time.** Razorpay documents the partner
  model, the "family pays the charges" setting and its Route limits most clearly; Cashfree is a
  little cheaper (1.95% against 2% [4][12]). Whichever confirms our flow in writing is used. The
  code talks to the gateway through one small adapter, so the choice can change.
- **The fee:** 10% of the price, capped at ₹50, rounded down, paid by the family on top and shown
  before Pay. The **payment charges** (about 2.36% with GST) are a separate line, paid by the
  family at cost: if we carry them we lose money on every service above about ₹2,000.
- **The free way stays:** paying straight to the agyari's or mobed's own UPI ID, by the link or QR
  the app already makes. No fee, no charges, marked paid by hand.
- **First release (P1):** in the gateway's test mode, a family pays one agyari for one booking after
  All set; the webhook marks it paid; the ledger records it. **Then P2:** live with one willing
  agyari, only after the CA's answers.

**To settle first:** D10 says behdins are always free. A fee the family pays changes that
(question 1).

---

## 2. How the money flows

### Step by step (recommended model)

1. The panthaky connects the agyari's own gateway account in Settings, once. The gateway does the
   KYC.
2. A family's request reaches **All set** (R4, `docs/r4-behdin-design.md`). Only then does Pay
   appear: nobody pays before mobeds are confirmed.
3. The family sees the price, our service fee, the payment charges and the total, with the
   agyari's name, and taps Pay.
4. The gateway's own checkout opens (UPI, Indian cards, net banking). Card and UPI details never
   reach our server.
5. The gateway puts the price into the agyari's account and our fee into ours, keeps its charges,
   and sends our server a signed message (a webhook).
6. Our server checks it, marks the booking **Paid online**, writes the ledger, and tells the family
   and the panthaky.
7. The gateway pays the bank accounts on its cycle (usually one to three working days; Cashfree
   lists T+2 for vendors [11]; to confirm).

```
Family pays ₹1,076  (price 1,001 + service fee 50 + payment charges 25)
      |
      v
Gateway's own checkout page  (card and UPI details stay with the gateway)
      |
      +-- price ₹1,001 ----------> agyari's own bank account   (its account, its KYC)
      +-- service fee ₹50 -------> Mobed Diary's bank account  (platform fee or commission)
      +-- payment charges ₹25 ---> kept by the gateway
      +-- signed webhook --------> our server: "Paid online", ledger, notices
```

Only our own fee ever reaches our bank account.

### Who carries the payment charges

Assumptions: fee = 10% of the price, capped at ₹50, rounded down. Gateway charge 2% plus 18% GST =
2.36% of what the family pays (Razorpay's standard rate for UPI, Indian cards and net banking [4];
Cashfree 1.95% [12]). Through a gateway UPI is not free: the law sets no MDR on UPI, but gateways
charge their own platform fee on it [5]. Route adds 0.1% plus GST on what it passes on [4]
(Razorpay's worked example uses 0.25% [3]). Once we are GST-registered, ₹50 would include about
₹7.63 of GST (to confirm).

**A. We carry the charges** (needs Route, closed to us for now):

| Price | Fee | Family pays | Gateway 2.36% | Route 0.118% | Left for us |
|---|---|---|---|---|---|
| ₹251 | ₹25 | ₹276 | ₹6.51 | ₹0.30 | ₹18.19 |
| ₹501 | ₹50 | ₹551 | ₹13.00 | ₹0.59 | ₹36.41 |
| ₹1,001 | ₹50 | ₹1,051 | ₹24.80 | ₹1.18 | ₹24.02 |
| ₹5,001 | ₹50 | ₹5,051 | ₹119.20 | ₹5.90 | **−₹75.10** |

We lose money on every payment above about ₹1,970.

**B. The family pays the charges, on their own line** (recommended). Charges are 2.36% of price
plus fee, rounded up (the gateway's exact sum may differ slightly):

| Price | Service fee | Payment charges | Family pays | Agyari gets | We get |
|---|---|---|---|---|---|
| ₹251 | ₹25 | ₹7 | ₹283 | ₹251 | ₹25 |
| ₹501 | ₹50 | ₹14 | ₹565 | ₹501 | ₹50 |
| ₹1,001 | ₹50 | ₹25 | ₹1,076 | ₹1,001 | ₹50 |
| ₹5,001 | ₹50 | ₹120 | ₹5,171 | ₹5,001 | ₹50 |

**C. The agyari carries them**, as with a card machine: on ₹1,001 it gets about ₹977. This breaks
"the mobed gets the full price".

**D. Direct UPI** (today's way, always offered): ₹1,001 to the agyari's UPI ID, nothing else.

New-merchant offers can make charges zero for a while (Razorpay: 90 days, up to ₹5 lakh, for
merchants activated from 1 Jul 2026 [6]; Cashfree: the first ₹20 lakh during an offer [12]). The
plan must work without them.

---

## 3. The fee

### Options

- **A service fee the family pays on top** (the owner's preference). The mobed gets the full price.
- **A commission out of the payout.** The family pays exactly the price; the agyari agrees to a cut
  in writing. Simpler for families, but the mobed no longer gets the full price.
- **A subscription for agyaries.** D4 already foresees paid automatic reminders, and D9's switch is
  ready for paying and not paying. It can sit beside either.

**Recommended:** the service fee on top; the subscription is a separate, later decision.

### How it is worked out

- **10% of the price, capped at ₹50, rounded down to the rupee.** No minimum: ₹101 pays ₹10.
- Worked out on the server from the price the panthaky set (`services.default_price`, R4.0), never
  from a number the phone sends. One fee per payment, not per mobed.

### How it is shown (consumer rules)

The E-Commerce Rules 2020 ask for the total as one figure with a breakup of every charge, plus the
business's name, a grievance officer and the refund policy [22]. The 2023 dark-patterns guidelines
ban revealing charges late ("drip pricing") and adding charges without consent ("basket
sneaking"); a necessary fee disclosed at purchase is allowed [23]. RBI also asks that charges on
top of the price are shown distinctly before paying [1]. So:

- The fee and charges are on **our own Pay screen, before the gateway opens**. Razorpay's own
  convenience-fee breakup appears only after Pay is tapped [9]: too late on its own.
- For example: **Jashan at <agyari>: ₹1,001. Service fee (Mobed Diary): ₹50. Payment charges (the
  payment company): ₹25. Total: ₹1,076.** One line says what the fee pays for. The receipt repeats
  the same lines.
- No pre-ticked boxes, no countdowns, no "add a donation".
- Beside Pay, always: **"Or pay <agyari> directly by UPI (no fees)"**.

### GST and refunds

- Our fee is our service to the family, so GST will likely apply once we are registered, commonly
  18% (to confirm: rate, code, families abroad). The shown fee **includes** any GST, so the total
  never changes at the last step.
- **For the pilot, a full refund returns everything**: price, fee and charges. It is the kindest
  rule, it avoids "cancellation charges" under the E-Commerce Rules (to confirm with the lawyer),
  and refunds will be rare because nobody pays before All set. On a partial refund the fee stays.

---

## 4. Who signs up with the gateway

### Options

- **Each agyari, as one account** (recommended first). It matches today: "payment stays with the
  panthaky" (D10). One KYC per temple. The panthaky decides whose bank account: the trust's or
  their own.
- **Each mobed**, for families in their own book. More KYC and support. Later, as an opt-in.

When two mobeds go, the family pays the agyari once, and the agyari pays its mobeds as today,
outside the app. Splitting between mobeds would be a third-party payment again [1].

### KYC (done by the gateway, never by us)

- **An individual:** PAN, an identity document such as Aadhaar, a bank account; maybe video KYC.
  Razorpay accepts businesses without GST and a savings account [10]. RBI allows a lighter check
  under ₹40 lakh a year: PAN, one identity document and an address check [1].
- **A trust:** its PAN, registration, deed, a bank account in its name, and the signatory's ID (to
  confirm per gateway). "Religious services" may need extra review (to confirm).
- The gateway's own pages collect the documents; we never see or store them.

### Without a bank account or PAN

The free way stays: the UPI link and QR (`agyaries.upi_id`, `qr_code_url`, `generate_upi_link()` in
`messaging/booking_service.py`), or cash. The money goes straight to them; they mark it paid by
hand, as today. The paid chip stays for this.

---

## 5. Automatic "paid"

### Webhooks

- One route on our server receives the gateway's events: payment captured or failed, refund
  processed or failed, settlement processed.
- **Every call is checked** against the gateway's signature (a secret only the gateway and our
  server know). A failed check is refused and changes nothing.
- **The phone's "success" screen is never trusted.** Only a checked webhook, or our server asking
  the gateway, marks anything paid.
- Amount, currency and our order number must match the order we made. A mismatch is not marked
  paid; the admins are shown it.

### The same event twice does no harm

- Every event is stored as it came, with its id unique. A repeat is answered "OK" and ignored.
- One open order per booking. A double payment by mistake is refunded automatically and shown to
  the admin.

### What the family sees

- **Paid:** "Paid ₹1,076 to <agyari>. Receipt."
- **Waiting** (UPI can take minutes): "Waiting for your bank. You need not pay again."
- **Failed:** "The payment did not go through. No money was taken." If money was taken anyway, the
  gateway returns it, and we say when, in the gateway's words.

### Cancellations and refunds (R4, section 5.5)

- **"We can't take this", or nobody can go:** everything back, automatically.
- **The family cancels:** everything back. Inside 24 hours the agyari's own rule applies, set by the
  panthaky and shown before paying. Default: everything back.
- **A mobed backs out and is not replaced:** the panthaky refunds part from the app.
- Refunds go **only through the gateway**, back to how the family paid.
- **Chargebacks** go to the agyari as the merchant, under the gateway's terms; we supply the All set
  record.

### Daily reconciliation

Every morning the server fetches yesterday's payments, refunds and settlements from the gateway and
compares them line by line with the ledger. Any mismatch goes to **Admin -> Payments** with a notice
to the admins. Nothing is fixed automatically: money moves only by a person, through the gateway.

---

## 6. The ledger and reports

### The ledger

- **Double-entry style:** each event writes lines that add up to zero. Amounts in paise, as whole
  numbers.
- **Append only:** a line is never changed or deleted; a mistake gets a reversing line.
- **Accounts:** gateway clearing; the agyari's money (recorded, not ours); our fee; GST on the fee;
  payment charges; refunds; and TCS and TDS if the CA says so.
- Each line keeps the gateway's ids, the booking, the agyari and the time.

Example, the ₹1,076 payment: gateway clearing +1,076; the agyari's money −1,001; our fee −50 (GST
−7.63 within it, if registered); payment charges −25. On payout, the agyari's money +1,001 and our
bank +50 against gateway clearing. Gateway clearing must return to zero: that is the daily check.

### Reports

- **Daily:** the reconciliation result.
- **Monthly, for the admin and the CA:** payments, refunds, fees (with and without GST), payment
  charges, bookings paid, and the tax totals the CA asks for. CSV and PDF.
- **Per agyari, monthly:** payments in, refunds, net, by date, for its confirmed panthakys.
- **Per mobed:** only once mobeds have accounts, seen by that mobed alone (D2).
- **Receipts:** one per payment, numbered in order each financial year, naming two suppliers: the
  agyari for the price and Mobed Diary for the fee. What each part must say is for the CA.

### Records, and D8

- D8 deletes nothing because of age, which suits money records: GST needs them kept at least 72
  months after the annual return's due date, and a company keeps eight financial years of books
  [24]; income tax has its own period (to confirm).
- **The conflict is with deletion on request** (D6, `docs/DATA-REQUESTS.md`). Recommended: ledger
  lines, amounts, receipt numbers and gateway ids stay; the person's name and number become
  "Erased". The privacy page says so (question 15).

---

## 7. Privacy and security

- **No card or UPI details touch our server**: only the gateway's hosted checkout. This keeps us out
  of most card-security (PCI) work.
- **Keys live only in the server's `.env`**, set by the owner; never in the code, the public
  repository, logs or screenshots. A setting `PAYMENTS_MODE` (off, test, live) picks test or live
  keys. Without keys there is no Pay button, and the screen says why.
- **Webhook signatures are checked** on every call.
- **The Content-Security-Policy** (`api/main.py`) needs the gateway's checkout script and frame.
- **The service worker never caches** a payment screen or receipt.
- **Every money route** uses `get_current_user` (D9). Refunds and connecting an account are for the
  agyari's confirmed panthakys and the admin only.
- **Who sees which amounts:**
  - a family: its own payments, receipts and refunds;
  - the agyari's confirmed panthakys: that agyari's payments and statement, no other's;
  - a mobed going on a booking: that the family paid the agyari, not the agyari's totals; a mobed's
    own earnings are theirs alone (D2), once mobeds have accounts;
  - a Doongerwadi manager: nothing about money;
  - the admin (the owner): everything, because the business keeps the accounts. The privacy page
    says so.
- **The gateway** is a new party seeing the family's payment details; the privacy page and terms
  name it (to confirm with the lawyer).

---

## 8. Build plan, in small releases

The Phase 2 rules hold: one helper per step, one piece per commit, only the nearest tests here
(GitHub runs the full suite), one browser walk-through per release on a scratch database (:8011),
and the owner's yes before each push. **P1 builds on R4.1** (family accounts, All set). If R4.1 is
not live, P1 can start with a pay link the panthaky sends a family from their own WhatsApp.

Kept as they are: the `payments` table (manual UPI and cash), `bookings.payment_status`,
`booking_mobeds.amount` and `is_paid`, the paid chip, `upi_id`, `qr_code_url` and
`generate_upi_link()`.

### P0. Paperwork and test mode (no code)

- Meet the CA with section 9; decide the business form, bank account and GST.
- The lawyer drafts terms for families, an agreement with agyaries (fee, refunds, chargebacks), and
  the privacy page (with LEG-11).
- Apply to Razorpay's partner programme and Cashfree's platform programme. Ask in writing: (1) is our
  flow allowed under RBI's 2025 rules for a platform under ₹40 lakh? (2) can our fee be taken from a
  small agyari's payment, or only paid as commission, and can it be a capped rupee amount? (3) can
  the family pay the charges, shown first on our screen? (4) can individuals and trusts without GST
  join, with which documents? (5) settlement timing, refunds and chargebacks; (6) every cost.
- The owner gets **test keys** and puts them in the server's `.env`.
- **Done when:** a gateway has answered in writing, the CA has answered questions 1-8, and the owner
  has answered rounds 1 and 2.

### P1. Pay a booking, in test mode only

1. A gateway adapter (Razorpay first) and `PAYMENTS_MODE`.
2. Tables: the agyari's gateway account; orders; the raw event log (unique event id); the ledger
   (append only); refunds. Migrations proved by `tests/test_migrations_run.py`.
3. Settings -> Payments for the panthaky: connect the account, see its status.
4. At All set, the family's Pay screen with the breakdown; the checkout; Waiting, Paid and Failed.
5. The webhook route: signature, repeats ignored, amount match, Paid online, ledger, notices.
6. Refunds for "We can't take this" and for a family's cancellation.

*Tests:* the fee for ₹101, ₹251, ₹501, ₹1,001 and ₹5,001 (rounding, cap); a bad signature changes
nothing; one event twice writes one set of lines; a wrong amount is not paid; each payment's lines
add to zero; only the agyari's confirmed panthakys see its payments; a manager sees nothing; an
account that is off can do nothing; no keys, no Pay button.
*Walk-through:* the gateway's test UPI and cards: pay, fail, pay twice, cancel, refund.

### P2. Live with one agyari

- The owner's yes; live keys set by the owner; an allow-list of agyaries (like
  `REMINDERS_ALLOWLIST`); a cap per payment (₹10,000 suggested); UPI, Indian cards and net banking
  only.
- The owner first pays a small real amount himself, and refunds it.
- The daily reconciliation job, read-only, with the admin notice.
- **Done when:** a month, or 30 payments, with no mismatch.

*Tests:* the allow-list, the cap, live mode refusing test keys and the reverse.
*Walk-through:* one real booking at the pilot agyari, from request to receipt, with its panthaky.

### P3. Ledger, reports and statements

Admin -> Payments with the monthly report and the CA's export; the agyari's statement; receipts as
PDF; GST, TCS and TDS summaries as the CA answered; "Erased" on request with amounts kept.
*Tests:* reports add up to the ledger; receipt numbers have no gaps; erasing keeps every amount.
*Walk-through:* a month of test payments, exported and read through with the CA.

### Later

More agyaries; mobeds' own accounts; the pay link for families not in the app; Route if our turnover
passes ₹40 lakh and it is worth it; the agyari subscription.

---

## 9. The CA checklist

Each: the question, why it matters, what we do with the answer.

1. **Business form.** Stay a sole proprietorship (the Udyam registration, `docs/STATUS.md`) or
   become an LLP or private limited company before going live? *Why:* liability, what gateways
   accept, record rules, some E-Commerce Rules duties. *Then:* register as advised before P2.
2. **Bank account.** A current account in the business's name? *Why:* our fees land there; mixing
   with personal money muddles the books. *Then:* open it in P0.
3. **Are we an "e-commerce operator" under GST?** *Why:* it can bring TCS and compulsory
   registration [16][18]. *Then:* register and file as told.
4. **Does TCS (section 52) apply** when the gateway pays the agyari's own account? The law speaks of
   payment the operator collects, and of taxable supplies only [16]; the rate is now 0.5% [17].
   *Then:* TCS lines in the ledger only if yes.
5. **GST registration.** Required now whatever our turnover (section 24 [18]), or only above the
   usual threshold (₹20 lakh for services in most states; to confirm)? Wise anyway? Must agyaries
   register (Notification 65/2017 [19])? *Then:* show "includes GST" only once registered.
6. **GST on our fee.** Rate (18%?), service code, families paying from abroad. *Then:* a
   GST-inclusive fee and the right receipt.
7. **Are the prayers GST-exempt** under "conduct of any religious ceremony" (Notification
   12/2017-CT(Rate), entry 13(a) [20])? Jashan, Afringan, Baaj, Machi, Navjote, weddings, funeral
   prayers? Is a Machi's sandalwood a sale of goods? Are none notified under section 9(5)? *Then:*
   word the agyari's part of the receipt as told.
8. **TDS by e-commerce operators** (section 194-O; under the Income-tax Act 2025, in force since 1
   Apr 2026, TDS sits in section 393 [21]). Rate 0.1% since 1 Oct 2024. A payment made straight to
   the seller counts as paid by the operator; resident individuals under ₹5 lakh a year with PAN or
   Aadhaar are exempt [21]. Does it apply to us, and to trusts? How do we deduct from money we
   never hold? Do we need a TAN? *Then:* build what it requires.
9. **Does any of this apply already** to today's free UPI link, or to R4's requests that show prices
   but take no money? *Then:* adjust R4.1 before it goes live.
10. **The agyari's money in our books**: recorded, never held. *Then:* shape the ledger to match.
11. **Our income tax:** fee income gross or net of charges; any simple scheme for a small business.
    *Then:* shape the monthly report.
12. **Receipts:** what we give the family for the fee (tax invoice, or a receipt while
    unregistered); what the agyari gives for the price; may we issue it for them; numbering. *Then:*
    build the receipt in P3.
13. **Refunds:** credit notes; refunded payment charges. *Then:* add the ledger lines.
14. **Records:** what to keep, in what form, how long (GST 72 months, company books eight years
    [24], income tax). *Then:* keep amounts and ids; erase names on request.
15. **E-Commerce Rules 2020** (with the lawyer): are we a "marketplace e-commerce entity"? What must
    we show? Does any duty need a company? *Then:* add the pages before P2.
16. **Dark patterns 2023** (with the lawyer): is the Pay screen clean, and is a "Payment charges"
    line acceptable? *Then:* change the screen if needed.
17. **RBI** (with the lawyer and gateway): confirm in writing that our flow does not make us a
    payment aggregator, which needs RBI authorisation and ₹15 crore of net worth [1]. *Then:* no
    live payments without it.

---

## 10. Questions for the owner

Each has a recommended answer.

### Round 1: the shape

1. D10 says **behdins are always free**. May families pay a **service fee** when paying through the
   app, while the app and paying the agyari directly by UPI stay free?
   *Recommended: yes; record it as a change to D10.*
2. Should the money go to **each agyari as one account** first, mobeds' own accounts later?
   *Recommended: yes.*
3. Should families pay **only after All set**? *Recommended: yes, with "pay later" allowed until
   the day after the prayers.*
4. Since Route is closed to small businesses, start with **each agyari as its own merchant**,
   Razorpay first and Cashfree alongside? *Recommended: yes.*

### Round 2: the fee

5. Is the fee **10% of the price, capped at ₹50, rounded down**, no minimum? *Recommended: yes.*
6. Should the family also pay the **payment charges** (about 2.4%), on their own line, at cost?
   *Recommended: yes; otherwise every service above about ₹2,000 loses money.*
7. Is **"Service fee"** the right name? *Recommended: yes, with one line on what it pays for.*
8. Should a full refund return **everything** (price, fee, charges), with the fee kept on a partial
   refund? *Recommended: yes, for the pilot.*

### Round 3: rules for money

9. A family's **cancellation** refunded in full, with the agyari's own rule inside 24 hours shown
   before paying? *Recommended: yes; default full refund.*
10. In the pilot, a **₹10,000 cap** per payment, and **UPI, Indian cards and net banking only**?
    *Recommended: yes.*
11. When a family pays online, the panthaky's request shows **"Paid online"** by itself, and each
    going mobed sees "The family has paid the agyari" without totals? *Recommended: yes; the
    mobed's own paid chip stays theirs.*
12. **"Pay <agyari> directly by UPI (no fees)"** always beside Pay? *Recommended: yes.*

### Round 4: business and records

13. The **business form** chosen on the CA's advice before going live? *Recommended: yes.*
14. **GST registration** before going live if the CA says it is required or wise?
    *Recommended: yes.*
15. Money records **kept for good (D8)**; on a deletion request, amounts and receipt numbers kept,
    name and number "Erased"? *Recommended: yes.*
16. **Admins see every amount**, a panthaky only their agyari's, a mobed only their own, a
    Doongerwadi nothing? *Recommended: yes, stated on the privacy page.*

### Round 5: the pilot

17. Which **one agyari** pilots it? *Recommended: one with a confirmed panthaky who wants it.*
18. Will you **pay a small real amount yourself** first, and refund it? *Recommended: yes.*
19. **Mobeds' own accounts** and the **pay link for families not in the app** after the pilot?
    *Recommended: yes.*
20. The **agyari subscription** (D4's paid reminders) a separate decision after the pilot?
    *Recommended: yes.*

---

## Sources (all looked at on 22 Nov 2026)

1. RBI, Master Direction on Regulation of Payment Aggregators, 15 Sep 2025 (RBI/DPSS/2025-26/141):
   https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12896 , read in the copy at
   https://www.fidcindia.org.in/wp-content/uploads/2025/09/RBI-PAYMENT-AGGREGATORS-DIRECTIONS-15-09-25.pdf :
   definitions (para 4); net worth ₹15 crore at application (Chapter II); charges shown before
   paying (para 10(c)); lighter KYC under ₹40 lakh (para 13(b)); money only to the merchant's
   account (para 13(g)); third-party payments only above ₹40 lakh turnover (escrow table,
   permitted debit iv).
2. Razorpay, Route FAQs (eligibility, RBI, 1 Jan 2026, refunds and reversals):
   https://razorpay.com/docs/payments/route/faqs
3. Razorpay, Route transfer fee examples: https://razorpay.com/docs/payments/route/transfer-fees-example.md
4. Razorpay, pricing (2% standard, UPI platform fee, Route 0.1%, no set-up or yearly fee):
   https://razorpay.com/pricing/
5. Razorpay blog, UPI MDR and platform fees: https://razorpay.com/blog/upi-charges-explained-mdr-vs-platform-fees/
6. Razorpay blog, 0% offer for new merchants:
   https://razorpay.com/blog/razorpay-0-percent-platform-fee-offer-90-days-new-merchants-2026/
7. Razorpay, partner commissions: https://razorpay.com/docs/partners/commissions.md
8. Razorpay, technology partners and control of funds: https://razorpay.com/docs/partners/technology-partners.md ,
   https://razorpay.com/docs/partners/technology-partners/control-of-funds.md
9. Razorpay, convenience fees: https://razorpay.com/docs/payments/dashboard/account-settings/configuration/convenience-fees ,
   https://razorpay.com/docs/payments/optimizer/convenience-fees (not with Route)
10. Razorpay, FAQs (no GST, savings account): https://razorpay.com/docs/payments/faqs.md ; KYC by
    business type: https://razorpay.com/docs/payments/business-types-kyc-documents/
11. Cashfree, Easy Split FAQ (0.2% per split, T+2 for vendors, refunds, up to five vendors per order):
    https://www.cashfree.com/docs/payments/split/faq
12. Cashfree, charges (1.95%, Easy Split 0.20-0.25%, offers): https://www.cashfree.com/payment-gateway-charges/
13. Cashfree, partners and merchant onboarding: https://www.cashfree.com/docs/partners/introduction ,
    https://www.cashfree.com/docs/partners/affiliates/partner-commissions-and-invoices
14. Other gateways, briefly: PayU's split settlement is on enterprise terms
    (https://inc42.com/flash-feed/payubiz-launches-splitsettle-payu); PhonePe offers split
    settlements (https://business.phonepe.com/split-settlements, not read in full). Not to start with.
15. Juspay's Hyperswitch routes between gateways and is not one itself
    (https://yourstory.com/2025/03/juspay-open-sources-payment-orchestrator-fintech-industry-shakeup-phonepe-razorpay).
    Too heavy for us.
16. CGST Act section 52: https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter10/section52_v1.00.html
    (would not load here; wording checked at https://www.advocatekhoj.com/library/bareacts/centralgstact/52.php)
17. Notification 15/2024-Central Tax, TCS 0.5% from 10 Jul 2024:
    https://gstcouncil.gov.in/sites/default/files/2024-09/central-tax-15-2024-11072024.pdf
18. CGST Act section 24, clause (x): https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter6/section24_v1.00.html
19. Notification 65/2017-Central Tax: https://gstcouncil.gov.in/node/3992
20. Notification 12/2017-Central Tax (Rate), consolidated, entry 13(a):
    https://gstcouncil.gov.in/sites/default/files/2024-02/12-exemption_cgst-01.04.2019-revised.pdf
21. TDS by e-commerce operators: 0.1% from 1 Oct 2024
    (https://inc42.com/buzz/budget-2024-tds-rate-for-ecommerce-operators-cut-to-0-1-from-1); the
    direct-payment and ₹5 lakh rules (https://www.taxmann.com/post/blog/tds-on-payment-by-e-commerce-operator-to-participants/,
    older, shows the earlier rate); the Income-tax Act 2025 from 1 Apr 2026
    (https://www.incometaxindia.gov.in/w/income-tax-act-2025-comes-into-force-from-1st-april-2026);
    TDS in section 393 (https://india-briefing.com/news/section-393-income-tax-act-2025-tds-rules-rates-compliance-guide-44450.html/).
    The new section's wording for operators is to confirm.
22. Consumer Protection (E-Commerce) Rules 2020, summary:
    https://www.lkslaw.com/insights/news/e-commerce-consumer-protection-e-commerce-rules-2020-notified
23. Dark Patterns Guidelines 2023, summary: https://www.barandbench.com/amp/story/view-point/ccpa-steps-in-to-curb-dark-patterns
24. Records: CGST section 36, 72 months (https://www.knowyourgst.com/gstlaw/cgst-act/36-period-of-retention-of-accounts-36/);
    Companies Act section 128(5), eight years (https://ca2013.com/128-books-of-account/).
