# Dr. Hassan Abbas Zaki Association: integrated management system, v2 framework

**Status:** draft for discussion · October 2026
**Scope:** CRM and fundraising, case management, projects, finance, HR and payroll, supply chain, with shared security, approvals (maker-checker) and Arabic/English throughout.

Confidence tags used below: **[Certain]** known fact or tested · **[Likely]** strong inference · **[Guessing]** an estimate to be validated.

---

## 0. Decisions to take before writing code

These choices change everything downstream. Each has a recommendation.

### 0.1 Build or adopt for finance, HR and payroll

| Option | What it means | For | Against |
|---|---|---|---|
| **A. Build everything** | Our own code for all six modules | The system is the association's own product (useful if it will be offered to other charities or investors); fits NGO workflows exactly | **[Likely]** the largest effort by far; accounting and Egyptian payroll mistakes carry legal and audit risk; needs an accountant and an HR/payroll specialist involved throughout |
| **B. Adopt an ERP (e.g. Odoo Community, free, open source, Arabic-ready)** | Use its accounting, HR, inventory, purchasing and project modules; build only the NGO-specific parts as add-ons | **[Likely]** much faster to a working finance/HR/stock system; proven double-entry accounting | Its look and workflows are generic; payroll localisation for Egypt still needs work; less ownership if the goal is a product to sell |
| **C. Hybrid (recommended if the system will be sold)** | Build the NGO core (CRM, cases, projects, fund accounting, in-kind aid, approvals), with a strict double-entry engine; build payroll last and have it validated by an Egyptian payroll accountant | Keeps ownership of what makes the product different; staged risk | Still large; finance must be designed right from day one |

**Recommendation:**
- If the only goal is to run the association, choose **B**.
- If the system is also a product (the investor walkthrough suggests it is), choose **C**, and do not go live on payroll until a professional has signed off on the calculations.

### 0.2 Architecture: a central server is required

**[Certain]** Six connected departments cannot each keep a separate copy of the data on their own PC, as the current single-PC mode does.

v2 needs **one central database** that every Windows PC and laptop connects to:
- **Office server.** One always-on PC or small server in the office. This is cheapest, the data stays in Egypt, and it works only inside the office.
- **Egypt-hosted cloud server.** This works from branches, homes and the field, and needs a monthly fee and a reliable internet connection.

Staff use a Windows desktop app (the same app in its own window, as today) or a browser. Field researchers use a phone or tablet app (section 7).

### 0.3 Rebuild the foundation now

**[Certain]** The current code is about 3,000 lines with a hand-made way of adding database columns. That approach will not survive six modules and hundreds of tables.

**Recommendation:**
- Move to **Django + PostgreSQL** for v2. It provides proper database migrations, built-in Arabic/English translation, a permission system, an admin back office, and a mature ecosystem.
- Port the existing CRM and case features into it. It is cheaper to switch now than after finance and HR exist.

### 0.4 Reading paper research forms automatically

See section 7. The short version:
- **[Likely]** Reading *handwritten Arabic* from a photo is not reliable enough to skip review. Even with review, it saves less time than a digital form.
- **The recommendation is a tablet/phone form that works offline, plus photo capture of documents.** Scanned paper forms with automatic field filling and mandatory human review are an add-on option, to be piloted on 50 real forms before committing.

### 0.5 Egyptian compliance needs named people

The system must respect the following. A **chartered accountant** and an **HR/payroll specialist** need to review the finance and payroll design before they are built:
- **NGO Law 149/2019** and its Executive Regulations: registers, reporting to the Ministry of Social Solidarity, and fund restrictions.
- Egyptian **income tax** on salaries, and **social insurance (Law 148/2019)**.
- **Personal Data Protection Law 151/2020**: beneficiary health and financial data counts as sensitive.
- Egyptian Accounting Standards.

**[Guessing]** The exact current rates, brackets and reporting formats change, so they must be held as configurable settings, never written into the code.

---

## 1. Architecture

```
                         ┌──────────────────────────────────────────┐
  Windows PCs/laptops ──▶│  Application server (office or cloud)    │
  (desktop app/browser)  │  ┌────────────────────────────────────┐  │
                         │  │ Platform: users, roles, approvals, │  │
  Field tablets/phones ─▶│  │ audit, documents, numbering, i18n  │  │
  (offline form app,     │  ├────────────────────────────────────┤  │
   syncs when online)    │  │ CRM │ Cases │ Projects │ Finance │  │  │
                         │  │ HR & Payroll │ Supply chain        │  │
                         │  └────────────────────────────────────┘  │
                         │  PostgreSQL · file storage · backups     │
                         └──────────────────────────────────────────┘
```

- **One codebase, modular.** Each module is a separate app with its own tables and screens. Modules talk to each other through defined services and events, never by editing each other's tables directly.
- **Every money movement ends in the General Ledger** through posting rules (section 4). That is what makes the system "seamless": nobody re-types a donation, salary or purchase into accounting.
- **Offline field app.** Researchers fill forms with no signal, and the forms sync later. Conflicts are resolved by the reviewer.
- **Deployment:**
  - One server, nightly encrypted backups kept off-site.
  - Windows installer for the desktop client.
  - Automatic updates from the server, so no one runs an old version.

---

## 2. Shared platform (built first, used by every module)

| Component | What it does |
|---|---|
| **Organisation master data** | Branches, departments, **cost centres**, **projects**, **funds** (restricted / unrestricted / zakat), fiscal years and periods |
| **Users and roles** | One login per person. Permissions work at three levels: the **module** ("can open Finance"), the **action** ("can post journal entries", "can approve PO up to EGP 50,000") and the **data scope** ("only own cases", "only Department X", "only Project Y") |
| **Maker-checker engine** | Configurable approval chains for any document type (section 6) |
| **Audit trail** | Who did what, when, from where, with old and new values; append-only |
| **Documents** | Attach files to any record. Versioning, document types, expiry dates (e.g. contracts, IDs) and access rules follow the record |
| **Numbering** | Official sequences per document type and year: receipts, vouchers, POs, GRNs, payslips, journal entries |
| **Bilingual UI** | Arabic (RTL) and English (LTR), switchable per user. Labels come from translation files. Names are stored in Arabic, with English optional. Reports print in either language |
| **Notifications** | An in-app inbox ("3 items waiting for your approval"), plus optional email or SMS |
| **Reporting** | Standard reports per module, Excel/PDF export, saved filters, and a management dashboard per role |

---

## 3. Modules

### 3.1 CRM and fundraising (exists in v1, to be extended)
- **Donors:** individuals and companies, contact history, communication preferences and consent.
- **Donations:** cash, bank, InstaPay, wallet, cheque, in-kind. Each gets a receipt, a purpose, and the **fund** it belongs to.
- **Campaigns:** Ramadan, Eid al-Adha, a surgery appeal, etc. Each has a target, a period, the donations received, and the beneficiaries or project it serves.
- **Pledges and sponsorships:** recurring commitments, with schedules, arrears and reminders.
- **Earmarking:** to a campaign, project, case or need (built in v1 for cases and needs).
- **Donor statements and thank-you letters.**

### 3.2 Case management (core built in v1)
- **Intake:** register the case, check for duplicates by national ID, and assign it to a researcher.
- **Field research:** digital form or uploaded paper form (section 7), family members, housing, health, income, debts, documents and photos.
- **Review:** researcher recommends, case manager approves, rejects or returns it (maker-checker).
- **Needs:** typed, prioritised, one-off or monthly, with a funding status.
- **Matching:** link needs to donors (sponsorship), to **campaigns**, or to restricted funds.
- **Disbursement request:** an approved case raises a cash or in-kind aid request. Finance pays it (cash) or the warehouse issues it (in-kind). Both feed back to the case history.
- **Periodic re-assessment:** e.g. every 12 months; the case goes back to research automatically.

### 3.3 Projects and programmes
- Projects and programmes with objectives, period, manager, donor or grant, and a **budget by budget line**.
- Activities, tasks, milestones, and the beneficiaries reached.
- **Budget vs actual** comes live from the ledger (every expense carries a project dimension).
- Staff time and cost allocated from HR (section 3.5). Purchases charged from supply chain.
- Donor or grant reports: spending per budget line, outputs, beneficiaries.

### 3.4 Finance
- **Chart of accounts** designed for an NGO, with **dimensions** on every line: cost centre, project, fund, donor (optional).
- **General Journal:** manual entries (maker-checker), plus automatic entries posted from the other modules.
- **Ledgers:**
  - General Ledger.
  - Sub-ledgers: cash and bank, vendors (payables), donor pledges (receivables), employee advances.
  - Expense ledgers by type.
- **Fund accounting:** restricted donations (zakat, orphan sponsorship, a specific project) can only be spent on matching purposes. The system blocks or flags violations.
- **Fixed assets:** register, categories, depreciation methods (straight-line by default), monthly depreciation run, disposal, and asset location/custodian (linked to HR).
- **Bank and cash:** receipts and payment vouchers, cheques, bank reconciliation, petty cash.
- **Budgets:** annual budget by account, cost centre and project, with variance reports.
- **Period close:** lock periods. Corrections only through reversing entries; no editing of posted entries.
- **Reports:**
  - Trial balance.
  - Statement of financial position (balance sheet).
  - Statement of activities (income and expenses), split by restricted and unrestricted funds.
  - Cash flow.
  - Ledgers and account statements.
  - Ministry reports in the formats it requires.

### 3.5 HR and payroll
- **Employee master:** personal data, national ID, contacts, emergency contact, bank account, and documents (contract, ID, certificates, insurance forms), with expiry alerts.
- **Organisation:** departments, positions, **job descriptions**, reporting lines.
- **Grades and pay structure:** salary scales per grade and step, allowances, deductions, benefits.
- **Contracts:** type, start and end, probation, renewals.
- **Attendance and leave:** leave types and balances, requests (maker-checker), and holidays.
- **Performance appraisals:** cycles, objectives, competencies, ratings, and manager and HR sign-off.
- **Payroll:**
  - Monthly run: gross, allowances, overtime, deductions, **social insurance**, **income tax**, net.
  - Payslips in Arabic and English.
  - Bank transfer file.
  - Every run requires maker-checker approval before posting.
- **Cost allocation:** each employee is assigned to departments or projects by percentage, or by timesheet. Payroll cost posts to the right cost centre and project automatically.

### 3.6 Supply chain
- **Item master:** food parcels, medicines, school kits, blankets, office supplies; units and categories.
- **Warehouses and locations:** stock on hand, minimum levels, batch and expiry (food and medicine).
- **Procurement:**
  - Purchase request → (quotations, with a 3-quote rule above a threshold) → purchase order → goods received note → vendor invoice → payment.
  - Three-way matching of PO, GRN and invoice.
  - Approval limits by amount.
- **Vendors:** register, documents, tax card, evaluation.
- **In-kind donations:** received into stock at fair value, with a receipt to the donor, and posted to finance.
- **Distribution:** issue to beneficiaries (linked to the approved case or campaign), distribution lists, signed or thumbprinted proof of receipt.
- **Logistics:** distribution trips, vehicles, drivers, routes.
- **Stock valuation** (weighted average) posts to finance; stock counts with variance approval.

---

## 4. How modules connect (posting rules)

| Event (module) | Accounting entry (Finance) | Other effects |
|---|---|---|
| Donation received (CRM) | Dr Cash/Bank · Cr Donation income (by fund: zakat / restricted / general) | Donor history; campaign and need progress |
| In-kind donation received (Supply) | Dr Inventory · Cr In-kind donation income | Stock in; donor receipt |
| Cash aid paid to a case (Cases → Finance) | Dr Aid expense (fund, project) · Cr Cash/Bank | Case aid history; need status |
| In-kind aid issued (Supply) | Dr Aid expense · Cr Inventory | Case history; stock out |
| Vendor invoice approved (Supply) | Dr Expense / Inventory / Asset · Cr Payables | Project budget consumed |
| Vendor paid (Finance) | Dr Payables · Cr Bank | |
| Payroll posted (HR) | Dr Salaries (by cost centre / project) · Cr Net pay payable, Tax payable, Social insurance payable | Payslips; bank file |
| Asset purchased (Supply/Finance) | Dr Fixed asset · Cr Payables/Bank | Asset register |
| Monthly depreciation (Finance) | Dr Depreciation expense (cost centre) · Cr Accumulated depreciation | |

The exact accounts and rules will be configured with the association's accountant. Nobody types these entries by hand.

---

## 5. Access model (examples)

| Role | Opens | Can approve | Sees |
|---|---|---|---|
| Field researcher | Cases (own), field app | — | Own cases only. No donors, amounts, HR or finance |
| Case manager | Cases, needs, matching, CRM (read) | Case approval; aid requests up to limit | All cases |
| Fundraising officer | CRM, campaigns, receipts | — | Donors, donations |
| Accountant | Finance (entries, vouchers, reconciliation) | — (maker) | Finance |
| Finance manager | Finance | Journal entries, payments, period close | Finance, budgets |
| Storekeeper | Warehouses, GRN, issues | — | Stock |
| Procurement officer | Requests, quotations, POs | — | Vendors, POs |
| HR officer | Employees, leave, documents | — (maker) | HR (no payroll amounts unless granted) |
| Payroll officer | Payroll | — (maker) | Salaries |
| Department / project manager | Own department or project | Leave, purchase requests, timesheets | Own department or project |
| Executive director / board | Dashboards, reports | Above-limit approvals | Summaries |
| System admin | Users, settings | — | Configuration (not salaries by default) |

---

## 6. Maker-checker controls

**Principle:** whoever *creates* a sensitive record cannot *approve* it, and the system enforces this, not people.

| Document | Maker | Checker(s) | Extra rule |
|---|---|---|---|
| New case / aid decision | Researcher | Case manager | Above EGP X → executive director |
| Cash aid disbursement | Case manager | Finance manager | Must link to an approved case and need |
| Manual journal entry | Accountant | Finance manager | Posted entries are never edited, only reversed |
| Payment voucher | Accountant | Finance manager + 2nd signatory above limit | Bank details cannot be changed by the same person who pays |
| Purchase order | Procurement | Department head → finance (by amount) | 3 quotations above threshold |
| Goods received | Storekeeper | Requester confirms | Cannot exceed PO quantity |
| Stock adjustment / write-off | Storekeeper | Finance manager | Reason required |
| Payroll run | Payroll officer | HR manager → finance manager | Changes vs last month highlighted |
| Salary / grade change | HR officer | HR manager | Effective-dated, history kept |
| New user / role change | Admin | Executive director (for finance/HR roles) | Logged |
| Donor bank / vendor bank change | Officer | Finance manager | A classic fraud point |

**Other checks built into the system:**
- Duplicate detection: national ID, vendor tax number, invoice number per vendor.
- Restricted-fund enforcement.
- Budget availability check before a PO.
- Period locks.
- Segregation-of-duties report: who holds conflicting permissions.
- Every approval is recorded in the audit trail, with an optional comment.

---

## 7. Field research capture (minimising work on the ground)

| Option | How it works | Effort for researchers | Data quality | Notes |
|---|---|---|---|---|
| **A. Offline digital form (recommended)** | The researcher fills a structured form on a phone or tablet during the visit (choice lists, numbers, photos of ID and documents, GPS and time). It syncs when online | Lowest after a week of practice: no re-typing at the office | High: validated as it is entered | Tablets cost money; some training needed |
| **B. Paper form, photo/scan, then automatic extraction** | Keep today's paper form (redesigned with boxes for each field). Photograph it; the system extracts the fields into a draft with each value marked by confidence; the researcher reviews and confirms | Low on site, moderate at review | **[Likely]** good for printed text and tick-boxes, unreliable for free handwritten Arabic, so every field must be reviewed | Needs an AI/OCR service. If that service is outside Egypt, beneficiary data leaves the country, so check the data-protection law and get consent. Pilot on 50 real forms before deciding |
| **C. Hybrid** | Digital form for structured fields, plus a photo of anything on paper (ID, medical report) attached | Low | High | A practical first step |

**Review screen (for B and C):**
- The scanned page sits beside the filled fields.
- Low-confidence fields are highlighted.
- The researcher must confirm before submitting, and the extracted values are kept in the audit trail.

**[Certain]** Nothing extracted automatically goes to approval without a human confirming it.

---

## 8. Bilingual design
- Every screen, message, report and document template exists in Arabic and English, and the user picks their language.
- Layout flips RTL/LTR automatically.
- Dates: Gregorian by default, with optional Hijri display (useful for zakat and Ramadan reporting).
- Numbers in Western digits by default, with Arabic-Indic digits optional on printouts.
- Names stored in Arabic (official), with English optional. Search works in both, and tolerates common spelling variants (أ/ا/إ, ة/ه, ي/ى).

---

## 9. Security and data protection
- Central server, HTTPS only, and the database never exposed to the internet.
- Daily encrypted backups off-site, with a quarterly restore test.
- Passwords plus optional two-factor login for finance, HR and admin roles.
- Field devices: app PIN, encrypted local storage, and remote logout if a device is lost.
- Sensitive fields (health, salaries, national ID) visible only to roles that need them; viewing salary and health data is logged.
- Retention rules per data type, and the right to correction under the data-protection law.

---

## 10. Phased delivery

**[Guessing]** The durations assume one experienced developer working with Claude, plus timely answers from the association. They will move once requirements are confirmed.

| Phase | Content | Depends on | Rough size |
|---|---|---|---|
| **0. Requirements and design** | Confirm this framework; collect real forms, chart of accounts, payroll rules, approval limits | Association staff, accountant | 2–4 weeks |
| **1. Platform + port CRM/Cases** | Django foundation, roles and data scopes, maker-checker engine, audit, documents, bilingual UI, server setup; move v1 data across | Phase 0 | 6–8 weeks |
| **2. Finance core** | Chart of accounts, journals, GL, cash/bank, vouchers, fund accounting, trial balance, statements, period close; posting from CRM and cases | Accountant's chart and rules | 8–10 weeks |
| **3. Field app + research capture** | Offline form app, sync, photo capture; pilot of paper extraction | Real forms | 4–6 weeks |
| **4. Supply chain** | Items, warehouses, procurement cycle, in-kind donations, distribution, valuation → GL | Phase 2 | 6–8 weeks |
| **5. Projects** | Projects, budgets, activities, budget vs actual | Phases 2, 4 | 4–6 weeks |
| **6. HR** | Employees, organisation, grades, contracts, documents, leave, appraisals | Phase 1 | 5–7 weeks |
| **7. Payroll** | Pay structure, tax and insurance rules, payroll run, payslips, cost allocation → GL; parallel run against the current payroll for 2–3 months before switching | Phase 6, payroll specialist | 6–8 weeks + parallel run |
| **8. Fixed assets, budgets, Ministry reports, dashboards** | | Phase 2 | 4–6 weeks |

**[Guessing]** That totals roughly 12–18 months to have every module in daily use. Each phase goes live on its own: the association benefits from phase 1 onward, and nothing waits for the whole.

---

## 11. What is needed from the association to start phase 0
1. **Approval of the options in section 0:** build vs adopt, office server vs cloud, digital form vs paper capture.
2. **The real research form,** paper or Excel, and 10–20 filled examples with personal data blacked out, for the capture pilot.
3. **The current chart of accounts,** the last audited financial statements, and the Ministry reporting formats used.
4. **Approval limits and who signs what today** (for section 6).
5. **The organisation chart,** grades and salary scales, and a sample payslip with names removed.
6. **Warehouse and procurement practice today:** forms, thresholds, how in-kind donations are recorded.
7. **A named owner per module** on the association side, who answers questions and accepts the work.
