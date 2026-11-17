# Phase 2: the Doongerwadi side (research and first design)

Research and design only: nothing here is built, and nothing here is decided. The owner's
decisions go into `docs/DECISIONS.md` when they are made. Written 17-18 Nov 2026.

Contents:
1. Why this is being considered (the mobeds' form)
2. The words, and what each one means
3. What happens after a death today
4. Where the funeral places are, and who runs them
5. How far the fire temples are from them, and a proposed rule for "near"
6. A first design for the owner to react to
7. Open questions for the owner
8. **The owner's answers (18 Nov 2026) and the design as it now stands.** Where section 8
   differs from sections 5-7, section 8 wins.

Supporting files in `docs/phase2-doongerwadi/`: the per-temple distance table
(`fire-temple-distances.csv`), the two scripts that made it (`geocode.py`, `distances.py`) and
the place lookups they used (`geocache.json`, town names and coordinates only).

---

## 1. Why this is being considered

The owner remembers that the need came up in the answers to a form sent to mobeds asking them to
list their problems. **Those answers no longer exist**: the owner checked and the Google file has
been deleted. Searched before that, with no trace: this repository (including the git-ignored
`docs/audit-2026-10-30/` and `docs/REVIEW.md`), `namebook-samples/`, the owner's Downloads,
Documents and Desktop, the owner's other project folders, and (with the owner's yes) Gmail.

So there are **no mobed quotes** to put here, and the need rests on the owner's memory. Before
anything is built, it would be worth getting it back on record in one of two ways (owner's
choice, see the questions in section 7):

- the owner writes down, in their own words, what they remember mobeds saying about deaths, the
  Doongerwadi and the dokhma; and/or
- a short conversation with two or three mobeds and one Doongerwadi office, using questions like
  these:
  1. When someone dies, how do you first hear about it, and from whom?
  2. Who finds the two mobeds for the Geh-saarnu, and how (calls, a WhatsApp group, a fixed rota)?
     How often is it hard to find them in time?
  3. Who arranges the Sarosh Baj at the fire temple in every geh until the Chahrum, and the four
     Baj-dharnas on the third night? How does the fire temple find out?
  4. For the Uthamna (five or seven mobeds), who calls the mobeds?
  5. What goes wrong most often in those four days?
  6. After the Chahrum, how does the family's own mobed get the date of death for the monthly and
     yearly prayers? Is it ever wrong (a death before sunrise, a Gatha day)?
  7. (For the Doongerwadi office) What do you write down when a death is reported? Who do you tell?
     What would you never want to share?

---

## 2. The words

The owner was unsure of the spellings. All of these are transliterations of Gujarati or
Avestan words, so several spellings are in use; the column "use in the app" is a suggestion.

| Use in the app | Other spellings seen | What it is |
|---|---|---|
| **Doongerwadi** | Dungerwadi, Doongarwadi, Dungarwadi | The whole funeral ground: the estate with the tower(s), the bunglis, the Sagdi and the gardens. Literally "hill garden" (Guj. *dungar* hill + *wadi* garden or compound). The name of the Mumbai estate on Malabar Hill; used for funeral grounds in other towns too. The Bombay Parsi Punchayet (BPP) writes "Doongerwadi". |
| **Dokhma** | Dakhma, dokhmu | The tower itself, where the body is laid. From Avestan *daxma*. Karanjia writes "Dakhma", the BPP and most Parsis write "Dokhma". |
| **Tower of Silence** | | The English name for a dokhma. Not a Parsi term: it is usually credited to a British colonial translator in Bombay, Robert Murphy, in the 19th century (sources differ on the year). |
| **Dokhmenashini** | Dokhmenashni | Laying the dead in a dokhma: the traditional way. |
| **Bungli** | Bunglee, Bangli, bunglow | A funeral bungalow at the Doongerwadi: the body is kept there, washed and dressed (Sachkar), the Geh-saarnu is prayed there, and in Mumbai the family can stay there for the four days. The Mumbai Doongerwadi has upper and lower bunglis (named after donors: Bhabha, Bennett, Wadia, Hodiwalla, Albless...). |
| **Prayer hall** | | Two different things: (a) the halls inside the Doongerwadi where the four days' prayers are held (Mumbai has 7 at the upper bunglis and 4 at the lower); (b) the **Worli Prayer Hall**, opened in 2015 inside the municipal crematorium at Worli, for families who choose cremation. In `fire_temples.json`, "Prayer Hall" is also the type of a few small Zoroastrian halls (Bhuj, Jamnagar, Calicut, London, Sydney, Tehran); these are not funeral places. |
| **Sagdi** | Sagri | A small building at the Doongerwadi with an unconsecrated (Dadgah) fire. Mourners offer it fuel and prayers after the funeral. The Mumbai one is about a hundred years old. |
| **Aramgah** | | A Zoroastrian burial ground ("place of rest"), used where there is no dokhma (Delhi, Chennai, and abroad). |
| **Khandia** / **Nasesalar** | Khandhia; Nassasalar | The corpse-bearers. Khandias carried the body; nasesalars laid it in the dokhma. Today the two are mostly one group. In small towns any Zoroastrian may do it with the ritual precautions. |
| **Sachkar** | Sachkār | The last bath and dressing of the body (sudreh and kasti, white shroud), laid on stone slabs. After it only the corpse-bearers may touch the body. |
| **Sagdid** | | A dog is brought to look at the body, at the start of each geh until the funeral. |
| **Geh-saarnu** | Geh-sarna, Gah-sārna | The funeral prayer: two mobeds recite the Ahunavad Gatha before the body, in daytime only. |
| **Paydast** | Pāydast, Pay-dast | The procession to the dokhma behind the body, in pairs joined by a cloth (paiwand), and the laying of the body in the dokhma. |
| **Sarosh nu Patru** | Sarosh-no-Kardo, Kardeh of Srosh | Two mobeds pray the Sarosh Yasht and Afringan in the night geh (Aiwisruthrem) on each of the first three nights. |
| **Uthamna** | Uthamnu | The third-day prayers: one in the afternoon (now mostly a condolence gathering, five or seven mobeds) and one before dawn of the fourth day. |
| **Chahrum** | Chaharum, Chehrum | The fourth day (morning): the Afringan of Dahm Yazad and the first commemorative prayers. |

---

## 3. What happens after a death today

Mainly from Ervad Dr Ramiyar Karanjia's "Death rituals" and his Q&A on death and Dokhmenashini
(ramiyarkaranjia.com), the chapter "Funerals and Post-Funerary Services" in *The Wiley Blackwell
Companion to Zoroastrianism* (Stausberg and Karanjia, 2015/2022), and the BPP's Doongerwadi page.
Local practice differs from town to town; this is the Mumbai pattern unless said otherwise.

**Reporting the death (Mumbai, from the BPP's page).** The family gets the doctor's medical
certificate of death (Form 4 for a death at home, 4A in hospital) and phones the Doongerwadi
office, which sends a hearse. The death is registered at the municipal ward office (D Ward,
Nana Chowk) for the registry certificate; a death outside Mumbai also needs police NOCs. The
family chooses **four days or one day** of obsequies, and is given a bungli "subject to
availability". **The Sachkar starts only after the Doongerwadi has a copy of the registry
certificate.** The office takes the certificate as a photo by WhatsApp. The Doongerwadi has over
100 staff in shifts: khandias, bungli kamdars, supervisors, gardeners, mortuary and solar
operators. It charges for the bungli (Rs 1,000 to 7,000), the hearse (by distance) and the
items used (sadra, shroud, sandalwood, loban and so on). There is also a separate dokhma for
Parsi women married outside the community who kept the faith.

**The first period, until the funeral** (the body should go the same day or the next):
1. Sachkar, by the Doongerwadi staff or relatives.
2. Sagdid at each geh.
3. A mobed (or, if none, a lay person) sits by the fire and recites from the Khordeh Avesta.
4. **Geh-saarnu, by two mobeds, in daytime only** (the BPP: after sunrise and up to an hour
   before sunset).
5. Sezdo: family and friends pay their respects.
6. Paydast: the procession to the dokhma behind the two Geh-saarnu mobeds; the nasesalars lay the
   body in the dokhma and the mourners finish the Sarosh Baj. Afterwards they visit the Sagdi.

**The second period, the first three days and the fourth morning:**
- **At a fire temple (agiary or Atash Behram): the Baj of Sarosh in every geh until the
  Chahrum.**
- At night (Aiwisruthrem geh), on each of the three nights: Sarosh nu Patru, by two mobeds.
- Third day, afternoon: **Uthamna**, five or seven mobeds, at the bungli (or the family's chosen
  place). Non-Parsis do not attend.
- Third night, before dawn: the night Uthamna (close family). **At the same time, at a fire
  temple, the four Baj-dharnas** (Rashn-Ashtad, Ram, Ardafravash and Sarosh).
- Fourth morning, **Chahrum**: Afringan of Dahm Yazad; if possible Yasna and Vendidad on the
  third day and night, and a **Machi** in the Havan geh of the fourth day, at the Sagdi or a fire
  temple.
- Then the commemorations: the tenth day, the thirtieth, the first monthly (Masiso), then yearly.
  **This is the part the app already handles** (memorials with their opening days 1-10, Masiso,
  monthly, yearly and Parabs).

**Where mobeds and fire temples fit.** In four days a single death needs at least: two mobeds for
the Geh-saarnu (at short notice, in daylight); two mobeds for each of three nights; five or seven
for the Uthamna; a fire temple to keep the Sarosh Baj in every geh and to do the four
Baj-dharnas on the third night; often a Machi on the fourth day; and then the family's mobed for
the memorial prayers for years. Who arranges each of these today, and how (the Doongerwadi's own
panel of mobeds, the family's mobed, phone calls, WhatsApp groups), was not found in any source.
That is the first question for mobeds and Doongerwadi offices (section 1).

**When there is no dokhma:** burial in an aramgah is accepted; cremation is rejected by many
orthodox Parsis but chosen by a growing minority. In Mumbai about 6% chose cremation before 2015
and about 12% after (Parsiana's editor, reported by Open magazine). The BPP has kept the
Doongerwadi bunglis for those going to the dokhma and has barred priests who prayed for the
cremated; that is why the Worli Prayer Hall was built (2015, at the Worli crematorium, funded by
the A.H. Wadia Trust, run by a Prayer Hall Trust, not the BPP). **Any design must not take a side
in this**: a family's mobed may pray for them whichever way the body goes.

**Vultures.** The vultures are almost gone (since the 1990s, poisoned by the veterinary drug
diclofenac, banned in 2006). The Mumbai dokhmas use solar concentrators (12 of them, four each at
three dokhmas), which work poorly in the monsoon. This changes nothing in the prayers, but it is
part of why some towns' dokhmas are little used.

---

## 4. Where the funeral places are, and who runs them

**Confidence matters here.** Mumbai is well documented; most other towns are not documented
online at all, and several sources are old. In 1906 India had about 120 dokhmas (Karanjia).
Which are still used today has to be confirmed with each town's Anjuman or Panchayat; the owner
and the mobeds will know their own towns better than any website.

| Place | Kind | Run by | Status | Sources |
|---|---|---|---|---|
| **Mumbai, Doongerwadi** (Malabar Hill, ~55 acres) | 6 dokhmas (Anjuman, Sethna and Bisni in use; Banaji not in use) + Modi dokhma; 11 prayer halls, upper and lower bunglis, Sagdi | Bombay Parsi Punchayet | **In use.** About 750-800 bodies a year (reported). | [BPP: Doongerwadi](https://bombayparsipunchayet.org/doongerwadi/); [Open: Khandias](https://openthemagazine.com/features/living/khandias-the-keepers-of-doongerwadi) |
| **Mumbai, Worli Prayer Hall** | prayer hall at the municipal crematorium | Prayer Hall Trust (A.H. Wadia Trust endowment) | In use since Aug 2015 (cremation route) | [Parsi Khabar, 2015](https://parsikhabar.net/bombay/reformist-parsis-get-a-funeral-prayer-hall-of-their-own-in-worli-mumbai-india/10844/); [HT, 2019](https://www.pressreader.com/india/hindustan-times-st-mumbai/20190222/281745565667975) |
| **Surat** | dokhma(s) and funeral parlour; Dokhma No. 3 reserved for COVID deaths in 2022 | Surat Parsi Panchayat Board | **In use as of 2022** (it went to the Supreme Court to keep Dokhmenashini for COVID deaths). Exact site: to confirm. A separate 1915 dokhma at Damka near Hazira was reported unused in 2011. | [ThePrint, Feb 2022](https://theprint.in/judiciary/sc-okays-protocols-for-handling-of-dead-bodies-of-zoroastrian-covid-19-victims/821844/); [Zoroastrians.net, 2011](https://zoroastrians.net/2011/08/14/can-we-revive-the-dokhma-at-surat/) |
| **Navsari** | dokhma | (Navsari Parsi Anjuman / Panchayat?) | **In use (the owner, 18 Nov 2026).** No current source online. | the owner |
| **Bilimora** | dokhma | ? | **In use (the owner).** Also listed by one weak source. | the owner; [study.com](https://study.com/academy/lesson/zoroastrian-tower-silence-history-use.html) |
| **Udvada** | dokhma outside the town | (Udvada Anjuman?) | **In use (the owner).** | the owner; [Caleidoscope](https://caleidoscope.in/offbeat-travel/unravelling-the-mystery-of-udvada-gujarat) |
| **Bharuch** | dokhma (very old) | ? | **In use (the owner).** | the owner |
| **Valsad, Sanjan, Ahmedabad, Vadodara, others in Gujarat** | ? | ? | Not found. **Owner to say** which towns have one. | |
| **Pune** | a smaller Doongerwadi | (Pune Parsi Panchayat?) | Exists. Site and use **to confirm.** | (secondary sources only) |
| **Secunderabad, Bhoiguda** | dokhma, consecrated 19 Oct 1839 | (Meherji family foundation) | In use per 2014-2017 reports; solar concentrators | [Parsi Times, 2025](https://parsi-times.com/2025/03/history-of-parsi-settlement-in-hyderabad-and-secunderabad/); [TalkDeath](https://www.talkdeath.com/we-are-still-believers-in-dokhmenashini-leaving-the-dead-for-vultures-in-india/); [Deccan Chronicle via Johbawa, 2017](https://johbawa.com/2017/01/12/parsis-in-hyderabad-prefer-tower-of-silence-for-the-departed/) |
| **Hyderabad, Zamistanpur** (Parsigutta) | dokhma | Parsi Zoroastrian Anjuman of Secunderabad and Hyderabad | In use per reports. Fewer than 500 families, about 20 deaths a year. | same |
| **Kolkata, Beleghata** | dokhma ("Cheel Ghar"), 1822 per one source | (Calcutta Parsi Zoroastrian Anjuman?) | Exists, under strain (about 500 Parsis). Use **to confirm.** | [Parsi Khabar](https://parsikhabar.net/issues/a-death-rite-at-peril/9588/) |
| **Bengaluru, Bellary Road** | dokhma, opened 23 Mar 1940 | Bangalore Parsee Zoroastrian Anjuman | Administered; rarely used (few deaths) | [Citizen Matters, 2010](https://citizenmatters.in/1858-parsee-history-dinshaw-cawasji/) |
| **Chennai, Royapuram** | aramgah (burial ground), in the Bagh | Madras Parsi Zarthosti Anjuman | In use | [MPZA](https://www.chennaizoroastrians.com/madras-parsi-zarthosti-anjuman) |
| **New Delhi** | aramgah (no dokhma) | Delhi Parsi Anjuman | Sources disagree on which ground takes burials now | [Parsiana](https://www.parsiana.com/current-issue/articles.aspx?id=D6ZzMQzT5kM%3D&issue=327); [Parsi Khabar](https://parsikhabar.net/india/the-delhi-parsi-aramgah/16795/) |
| **Karachi, Mehmoodabad** | dokhma (the older one no longer used) | Karachi Parsi Anjuman Trust Fund | In use per 2024 report | [Dialogue Pakistan, 2024](https://www.dialoguepakistan.com/en/pakistan/karachi-s-only--tower-of-silence--where-parsis-perform-funeral-rites-of-their-dead); [Scroll](https://scroll.in/article/1033887/175-years-after-parsis-flocked-to-karachi-glimpses-of-the-communitys-fading-history) |
| **Iran** | dokhmas closed (Yazd in 1974); burial in Zoroastrian cemeteries | | Not in use | [Wikipedia: Tower of Silence](https://en.wikipedia.org/wiki/Tower_of_Silence) |
| **Abroad** (UK, North America, Australia, Hong Kong...) | no dokhmas; cemeteries and cremation | local associations | not relevant to a first version | |

Background sources: Stausberg and Karanjia, "Funerals and Post-Funerary Services", in *The Wiley
Blackwell Companion to Zoroastrianism* (Wiley, 2015, corrected 2022), pp. 375-376;
Karanjia, [Death rituals](http://ramiyarkaranjia.com/death-rituals/) and
[QA about death and Dokhmenashini](http://ramiyarkaranjia.com/16-qa-about-death-and-dokhmenashini/);
[NPR on the vultures, 2012](https://www.npr.org/2012/09/05/160401322/vanishing-vultures-a-grave-matter-for-indias-parsis);
[Scroll on the cremation dispute](https://scroll.in/article/1000017/how-to-dispose-of-the-dead-this-and-many-other-controversies-feature-in-this-history-of-the-parsis);
[Open: A Burning Question](https://openthemagazine.com/art-culture/a-burning-question).

---

## 5. How far the fire temples are, and a proposed rule for "near"

### How the numbers were made

- `src/agyary/scripts/data/fire_temples.json` (167 temples, from a 2012 community spreadsheet)
  has a name, type, address, city and state, but **no coordinates**. Each temple's town or village
  was looked up on OpenStreetMap (76 places, only names sent). Three lookups landed in the wrong
  place (Bordi, Thane, Valsad) and were corrected by hand. Mumbai's 45 temples were placed by
  neighbourhood (Fort, Dhobi Talao, Tardeo, Dadar, Bandra, Andheri...) by hand; two (Cama Baug,
  Contractor Baug) are at the city centre because their neighbourhood was not certain.
- The funeral places are the 15 in section 4 that have a known town, placed at town or
  neighbourhood level. **Where a place's use is unconfirmed (Navsari, Bilimora, Udvada, Bharuch,
  Pune, Kolkata) it is still counted**, so the numbers show the most that could be "near".
- Distances are straight-line ("as the crow flies"). Road distance is usually 1.2 to 1.5 times
  more. The positions are good to a few km, enough to choose a rule, not to print an address.
- Of the 167 temples, 154 are in India and Pakistan; the 13 abroad (Iran, London, Toronto,
  Vancouver, Sydney, Hong Kong, Colombo) are left out of the counts.
- The 2012 list misses temples built or opened since, and may list some that have closed.

Full per-temple table: `docs/phase2-doongerwadi/fire-temple-distances.csv`.

### What the numbers show

**Fire temples by their nearest funeral place** (154 temples):

| Nearest funeral place | Temples | Median distance | Furthest |
|---|---:|---:|---:|
| Mumbai, Doongerwadi | 36 | 2.2 km | 16.3 km |
| Mumbai, Worli Prayer Hall | 13 | 7.7 km | 109.5 km (Igatpuri) |
| Surat | 27 | 1.8 km | 29.2 km |
| Navsari | 11 | 0.1 km | 50.6 km (Vyara) |
| Bilimora | 5 | 4.9 km | 20.0 km |
| Udvada | 15 | 31.6 km | 114.1 km (Deolali) |
| Bharuch | 18 | 88.5 km | 394.4 km (Neemuch) |
| Pune | 9 | 66.6 km | 304.2 km (Belgaum) |
| Secunderabad / Hyderabad | 5 | 6.2 km (Hyderabad's own) | 419.5 km (Nagpur) |
| Kolkata | 2 | 226 km | 226 km (Jamshedpur) |
| Bengaluru | 3 | 279 km | 370 km (Hubli) |
| Chennai (aramgah) | 1 | 3.6 km | 3.6 km |
| New Delhi (aramgah) | 5 | 388 km | 577 km (Allahabad) |
| Karachi | 4 | 317 km | 595 km (Quetta) |

All 45 Mumbai temples are within **20.5 km** of the Doongerwadi (median 2.7 km; the furthest are
Andheri and Jogeshwari). The suburbs outside the city are further: Uran 16 km, Thane 32 km,
Kalyan 47 km, Lonavla 67 km, Boisar 94 km, Dahanu 115 km.

**How far each temple is from its nearest funeral place:**

| Distance | Temples | Running total |
|---|---:|---:|
| under 5 km | 86 | 86 (56%) |
| 5-10 km | 16 | 102 (66%) |
| 10-15 km | 2 | 104 (68%) |
| 15-20 km | 5 | 109 (71%) |
| 20-30 km | 6 | 115 (75%) |
| 30-50 km | 6 | 121 (79%) |
| 50-100 km | 8 | 129 (84%) |
| 100 km or more | 25 | 154 (100%) |

Two thirds of the fire temples are in the same town as a funeral place. Then there is a gap: very
few are 10-50 km away. The last quarter are in towns with a fire temple but no funeral place
(Ahmedabad, Vadodara, Rajkot, Nagpur, Indore, Ajmer, Kanpur...), 50 to 600 km from the nearest.

**How far apart the funeral places are** (the ones close enough to overlap):

| | | Distance |
|---|---|---:|
| Secunderabad (Bhoiguda) | Hyderabad (Zamistanpur) | 1.6 km |
| Mumbai Doongerwadi | Worli Prayer Hall | 5.6 km |
| Navsari | Bilimora | 20.9 km |
| Surat | Navsari | 29.2 km |
| Bilimora | Udvada | 33.6 km |
| Surat | Bilimora | 49.9 km |
| Navsari | Udvada | 53.6 km |
| Surat | Bharuch | 59.7 km |

**Testing a plain radius** ("every fire temple within R km"), counting a temple as "in two
places' circles" only when the places are in different towns (Mumbai's two count as one town, and
so do Hyderabad's two):

| R | Temples covered | In two different towns' circles |
|---:|---:|---:|
| 15 km | 104 (68%) | **0** |
| 20 km | 110 (71%) | 4 (Gandevi, Bhatha, two in Valsad) |
| 25 km | 112 (73%) | 13 |
| 30 km | 115 (75%) | 19 (Navsari's own temples start falling in Surat's circle) |

### Proposed rule

> **Replaced by the owner's answer (section 8):** there is no fixed list. The manager sees every
> agyari in the app, with a "Suggested" section sorted nearest first, and every agyari gets a
> proper location picked on a map. The numbers above are kept as background: they show that
> nearest-first puts each town's own agyaries at the top.

**"Same town, or within 15 km", worked out once as a suggestion, then confirmed and adjusted by a
person and stored as a fixed list.**

- 15 km covers every temple that is in a funeral place's own town, Mumbai's whole city
  (bar the two Andheri / Jogeshwari temples at 20 km, which "same town" catches), and puts **no
  temple in two towns' lists**. 20 km would start pulling Gandevi and Valsad into two lists; 30
  km would put Navsari's own temples in Surat's.
- A radius alone is not enough either way: Thane (32 km) and Kalyan (47 km) probably belong with
  the Mumbai Doongerwadi, and Valsad (17 km from Udvada) may go to Udvada or nowhere, depending on
  local custom. So the suggestion is only the starting list. **The admin (or the Doongerwadi's
  manager) ticks the final list**, and the app stores the links rather than working them out every
  time. This also means the app never needs map coordinates for fire temples: the analysis here
  is enough to make the first suggestions.
- The quarter of temples far from any funeral place belong to no Doongerwadi at first. Their
  mobeds are still reached through the family's own mobed (section 6).

---

## 6. A first design, for the owner to react to

> **First draft.** The owner reacted to it on 18 Nov 2026; section 8 has the design as it now
> stands. Kept here because most of it (the fields, what is not recorded, privacy, D2) still holds.

Everything below is a proposal. Where a choice is the owner's, it is in section 7.

### Who the new users are

- **A funeral place** (new record): a Doongerwadi, an aramgah or a prayer hall. Name, town, kind,
  who runs it (BPP, Surat Parsi Panchayat...), and its list of linked fire temples (section 5).
  The admin creates it; nobody can add one themselves.
- **Doongerwadi manager** (new kind of account): signs in with WhatsApp like a mobed, says which
  funeral place they work for, and **waits for the admin's approval** (D9 as it is today). Has the
  same single on/off switch. The admin should check with the trust's office that the person really
  works there before approving (see section 7).
- **Doongerwadi staff** (later, not in the first version): an office clerk or bungli kamdar who
  records deaths but cannot change the linked fire temples or the staff list. In the first version,
  the manager does everything.
- Mobeds, panthakys and fire temples stay as they are. A mobed does not need to do anything new to
  be reachable: they are already linked to their fire temple.

### What the Doongerwadi records when a death is reported

Only what is needed to arrange the prayers. A **funeral record**:

| Field | Why |
|---|---|
| The departed's name as it is prayed (title such as Behdin / Ervad / Osta, own name, father's or husband's name) | Mobeds recite it. The app already has these titles. |
| Date of death **and its Roj and Mah** | The memorial dates count from it; D5's rule (a death before sunrise is the previous Parsi day) applies, so the Roj and Mah are shown for the manager to confirm. |
| Four days or one day | Decides which prayers follow. |
| Bungli (or prayer hall) | Where the mobeds go. |
| Geh-saarnu: day and geh | The urgent one. |
| Uthamna: day and time, number of mobeds wanted | |
| Whether a fire temple is asked for the Sarosh Baj and the four Baj-dharnas, and which one | |
| The family's mobed, if the family names one | See "the family's own mobed" below. |
| One family contact: name and number | Only the manager and assigned mobeds see it. |

**Not recorded:** cause of death, age, address, the death certificate or its photo, Aadhaar or
other ID numbers, and the way the body goes (dokhma, burial or cremation), except that the record
belongs to the place where the prayers are.

### How it reaches mobeds and fire temples nearby

1. The manager saves the funeral record and presses **"Ask for mobeds"**.
2. A **notice** goes, in the app and as a phone notification (the same web push the admin already
   gets for a waiting mobed), to the panthakys of the linked fire temples and to the mobeds who
   chose those temples. It shows only: the departed's prayed name, the bungli, which prayers, when,
   and how many mobeds are wanted. **Not the family's number.**
3. A mobed taps **"I can come"** for a given prayer. The manager sees who offered and confirms
   (the app already has "assigned / accepted / declined" for bookings, which this can reuse).
   Once confirmed, the prayer goes on that mobed's calendar and the mobed sees the family contact.
4. The fire temple asked for the Sarosh Baj and Baj-dharnas gets its own notice with the times;
   its panthaky confirms.
5. When everything is covered, the notice closes for everyone else.

This is in-app plus phone notification only. **No WhatsApp messages from our number to mobeds or
to the family in the first version**: that would need new Meta templates, and messages to the
family need consent (next point).

### The family's own mobed, the memorial, and the reminders

- The family may name their mobed. The manager picks that mobed from the approved mobeds of the
  linked fire temples (or searches by name), and that mobed gets a direct notice.
- **The Doongerwadi can never see which mobed has which family** (D2: behdins are private to their
  mobed). Typing the family's number must not reveal or link anything, the same rule as AZ-3.
- The family's mobed can press **"Make a memorial from this"**: it opens the existing memorial form
  in *their own* behdin book, with the name, date, Roj and Mah filled in. From then on it is an
  ordinary memorial (opening days 1-10, Masiso, monthly, yearly, Parabs). The Doongerwadi's record
  and the mobed's memorial are separate copies: editing one does not change the other.
- **Reminders stay exactly as they are.** A family gets automatic WhatsApp reminders only if their
  mobed records, in person, that they agreed (the consent words, `reminders_consent_version`); a
  number written down at the Doongerwadi is not consent. The opening ten days are never reminded
  (D4). A STOP stays global.
- The manager may send the family the times **by hand** from the manager's own WhatsApp (the
  existing "send by hand" button), as mobeds do now.

### Privacy

- A funeral record is seen only by that funeral place's manager (and later, staff), and the
  details needed by each mobed or fire temple who is asked. The family's number only by those
  confirmed. Admins see counts, not names, unless a family asks about their data
  (`docs/DATA-REQUESTS.md`).
- D8 applies: nothing is deleted for age. A funeral record stays until someone asks for it to be
  removed. The owner should confirm this is right for funeral records too (section 7).
- The lawyer's open questions (REVIEW and the audit's LEG-11: whether a departed person's name and
  date of death are personal data under India's data protection law, and whose) apply even more
  here. They should be answered before a Doongerwadi uses this with real deaths.
- The repo is public: no real funeral place's staff names or numbers go into the code or docs.

### What it does not do (on purpose, at first)

- No public list of deaths or Uthamna notices (newspapers do this; the app should not, unless the
  owner decides otherwise).
- No payments, bungli bookings or hearse requests: the Doongerwadi office keeps those.
- No ruling on cremation: the app records prayers, not how the body goes.
- No staff accounts, no WhatsApp templates, no places abroad.

### Suggested order

1. **Get the need back on record** (section 1) and pick **one pilot place** with a willing manager.
2. Admin: create the funeral place; suggest and confirm its fire temple list (section 5).
3. Manager accounts with approval (reusing D9's approval and switch).
4. The funeral record and "Ask for mobeds", in-app and phone notification.
5. "Make a memorial from this" for the family's mobed.
6. Later: staff accounts; WhatsApp templates (if the pilot asks for them); more places.

---

## 7. Open questions for the owner

1. **The need.** With the form's answers gone, will you write down what you remember mobeds
   saying, and/or talk to two or three mobeds and one Doongerwadi office with the questions in
   section 1 before anything is built?
2. **The pilot place.** Which Doongerwadi first, and do you know its manager? (Mumbai's is the
   largest and best organised but run by the BPP with its own rules; Surat or Navsari may be
   easier to start with.)
3. **Which towns' dokhmas are really in use?** Navsari, Bilimora, Udvada, Bharuch, Pune, Kolkata
   and any others: can you or the mobeds confirm, and name who runs each?
4. **Who arranges the mobeds today?** Does a Doongerwadi have its own panel of mobeds for the
   Geh-saarnu, or does the family's mobed arrange everything? This decides who presses "Ask for
   mobeds".
5. **The "near" rule.** Same town or within 15 km as the first suggestion, then you (or the
   manager) tick the final list: agreed? Should Thane and Kalyan go with the Mumbai Doongerwadi?
6. **Who checks a manager is real** before approval: you, by calling the trust's office?
7. **Cremation and the Worli Prayer Hall.** Should a prayer hall for the cremated be a funeral
   place in the app like a Doongerwadi? (The app would take no side; but it is your call.)
8. **What mobeds see.** Is the departed's prayed name, bungli and times enough for the notice, and
   the family's number only once confirmed?
9. **Keeping funeral records.** D8 says nothing is deleted for age. Is that right for funeral
   records too, or should a Doongerwadi's records close after the Chahrum?
10. **Words.** Are the spellings in section 2 the ones you want in the app (Doongerwadi, Dokhma,
    Bungli, Geh-saarnu, Uthamna, Chahrum)? And in Gujarati?
11. **Money.** Free for Doongerwadis, or part of the paid plan later (D4, D9)?

---

## 8. The owner's answers (18 Nov 2026) and the design as it now stands

These are the owner's answers to section 7, in the owner's sense, with what follows from them.
Recorded as **D10** in `docs/DECISIONS.md` (18 Nov 2026).

### The answers

| # | Question | The owner's answer |
|---|---|---|
| 1 | The need | **The owner will write down what they remember** mobeds saying. No interviews for now. |
| 2 | Pilot place | **The Mumbai Doongerwadi** (Bombay Parsi Punchayet). |
| 3 | Dokhmas in use | **Navsari, Udvada, Bilimora and Bharuch are in use**, as well as Mumbai and Surat. |
| 4 | Who arranges the mobeds today | **A mix.** Many families have their own preferred agyari, and its **panthaky** arranges the prayers. Sometimes the **Doongerwadi manager** contacts the panthakys. Families who choose cremation often do not have their prayers at an agyari. |
| 5 | Which agyaries are "near" | **No fixed list.** The manager sees **every agyari in the app**: a **"Suggested" section** nearest first (for example within 500 km), and a search over all of them. **Every agyari gets a proper location**, picked on a map when its address is added or set up. |
| 6 | Who gets the request | **The panthaky of the chosen agyari.** If that agyari has no panthaky in the app, **all its enrolled mobeds** get it. Agyaries with two or more panthakys are a hard case, to be settled in the mobed / panthaky / fire temple version (Version 3). |
| 7 | Mobed or panthaky | **At sign-up, a person chooses whether they are a mobed or a panthaky.** For now everyone can use every feature; the roles' rights and limits come in Version 3. Anyone (mobed or panthaky) can set up a fire temple. (Panthaky must be confirmed by the owner at approval; see point 2 below.) |
| 8 | The request on the agyari's side | A **distinct place in the app with a red dot and a count**. The panthaky **accepts**, and accepting **sets everything up for them**: the departed's name, the date, and **the behdin's name and number come across from the Doongerwadi**, so the behdin and the memorial are made for them. |
| 9 | Family's agreement to share | **Yes, a tick:** the manager ticks that the family agreed to share their name and number with that agyari before the request can go. |
| 10 | Reminders | **Keep the rule.** The behdin arrives with reminders off; the mobed turns them on after asking the family in person, as today. |
| 11 | Checking a manager | **The same as mobeds:** the manager signs up, appears on the admin side with name and number, and the owner gives access. |
| 12 | The Worli Prayer Hall | **Yes, alongside the Doongerwadi** from the start. |
| 13 | Who uses the Doongerwadi end | **The manager, for now.** A family (behdin) version comes later. |
| 14 | Keeping funeral records | **Keep, like D8**: nothing deleted for age. |
| 15 | Money | **Doongerwadis and the Worli Prayer Hall are free.** Agyaries are the paying customers; behdins will always be free. |
| 16 | Access and payment | Access by payment status (per agyari) is **to be discussed properly, in depth**, as part of the mobed / panthaky / fire temple version. Much of it the owner will do by hand from the admin side. Until then the per-person switch (D9) stays as it is. |
| 17 | Spellings | **As suggested:** Doongerwadi, Dokhma, Bungli, Geh-saarnu, Uthamna, Chahrum, Sachkar, Paydast, Aramgah. |

### Phase 2 as it now stands

**1. Every agyari gets a location.**
- A map pin (latitude and longitude) on each fire temple, chosen by tapping a map when the address
  is added or edited (for example OpenStreetMap, which needs no paid key).
- The 167 agyaries already in the app start from the town (or, in Mumbai, neighbourhood)
  positions worked out in section 5, good to a few km. Each agyari can correct its own pin later.
  The admin can see which pins are still town-level.

**2. Sign-up asks "mobed or panthaky".**
- **Care needed:** the app already has a role on each person's link to their fire temple
  (`agyary_users.role`: panthaky, mobed, caretaker), and **"panthaky" is a privilege today**: a
  panthaky sees every mobed's machis at that temple (D7). On purpose, nothing in the app lets a
  person give themselves that role (`services/mobed_auth.py`). So the sign-up answer must be
  stored as a **claim** ("says they are the panthaky"), shown to the owner on the approval screen,
  and become the real role only when the owner confirms it. Otherwise anyone could sign up as
  panthaky of any temple and see its machis, and receive its families' requests.
- Apart from that it changes nothing a person can do yet (Version 3 decides that). It decides one
  thing in Phase 2: who gets a Doongerwadi's request (confirmed panthakys first).

**3. Funeral places and their managers.**
- The admin creates the funeral places: the Mumbai Doongerwadi and the Worli Prayer Hall to begin
  with.
- A manager signs in with WhatsApp, chooses their funeral place, and waits. They appear on the
  admin side next to new mobeds (name, number, place), and the owner approves them. The same
  single on/off switch applies (D9).
- The admin side gains a view of what is enrolled: mobeds, panthakys, funeral places and their
  managers, and fire temples.

**4. Recording a death and sending the request (the manager).**
- The manager fills in the funeral record (section 6: the prayed name, date with Roj and Mah,
  four days or one, bungli, Geh-saarnu and Uthamna times, and one family contact).
- They then choose an agyari: **Suggested** (nearest first, within 500 km) or **search all**.
  The family's preferred agyari goes first when they have one.
- Before sending, the tick: *"The family agreed to share their name and number with this
  agyari."* The request cannot go without it.
- The request goes to that agyari's panthaky (or panthakys). If it has none in the app, it goes to
  all its approved mobeds.

**5. The request on the agyari's side.**
- A **Requests** place in the app with a red dot and a count, plus a phone notification (the same
  web push the admin already gets). Before accepting, it shows the departed's prayed name, the
  funeral place and bungli, the prayers and their times. The family's number is not shown yet.
- **Accept** does the setting up in the accepting person's *own* book:
  - the behdin is made with the family's name and number, or, if that number is already in
    *their own* book, that record is used (nobody else's book is ever looked at, D2);
  - the memorial is made with the departed's name, the date, and the Roj and Mah, for them to
    check and save as today;
  - the four days' prayers go on their calendar.
  - Reminders stay off until they ask the family (D4, consent rule).
- **Decline**, or no answer: the manager sees it and can choose another agyari.
- The manager sees who accepted.

**6. What stays out of Phase 2:** staff accounts at the Doongerwadi; the family (behdin)
version; roles' rights and payment per agyari (Version 3); WhatsApp messages from our number for
any of this; other funeral places until the pilot works.

### Still to settle (smaller, can wait until building)

1. **Two or more panthakys at one agyari:** for Phase 2, do all of them get the request, with
   the first to accept taking it? (The owner says the full answer belongs to Version 3.)
2. **How long a request waits** before the manager is prompted to pick another agyari (an hour?
   for the Geh-saarnu, much less?).
3. **What a cremation family's record looks like at Worli:** the same fields, but the prayers
   offered may differ (often no Sarosh Baj at an agyari). The Worli Prayer Hall's manager would
   say.
4. **Mumbai's own process:** the BPP office takes the death certificate on WhatsApp and assigns
   the bungli. The app should fit around that, not replace it. This is worth a conversation with
   the Doongerwadi office before building.
5. ~~Recording the decisions~~: done, D10 in `docs/DECISIONS.md` (18 Nov 2026).

### The owner's longer view (not Phase 2)

- **A family (behdin) version**, free: a behdin chooses among the agyaries and Atash Behrams
  enrolled in the app and asks for what they need, and the request reaches the agyari's side the
  same way as a Doongerwadi's. Agyaries pay; behdins never do.
- Later: **Parsi knowledge for behdins** (the owner's `parsi-kg` project) and **a daily note
  about the religion** to interest people in it. A daily WhatsApp message would count as
  marketing under Meta's rules, with its own opt-in and cost, so it would most likely live in the
  app (or as a notification) rather than on WhatsApp. To be designed then.
