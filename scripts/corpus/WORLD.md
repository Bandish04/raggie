# Nebula Teknoloji — world bible for the synthetic corpus

Single source of truth for the facts the sample corpus states. Every document
in `content/*.py` must agree with this file; facts that appear in more than one
document are listed here so the documents stay consistent (multi-hop questions
depend on it). Everything is fictional; domains use RFC 2606 (`nebulacrm.example`).
No real companies, brands, products or people (generic technology names such as
PostgreSQL, Kubernetes, Kafka, ISO/IEC 27001, KVKK are fine).

Number style: Turkish documents write `2.750 TL`, `%15`, `99,9`, dates `17 Nisan 2026`
or `17.04.2026`; English documents write `TRY 2,750` / `$22.4M`, `15%`, `99.9%`,
`17 April 2026`. XLSX money columns hold plain integers (`2750`) with the unit in the
column header.

## Company

- Nebula Teknoloji A.Ş., founded 11 Mart 2014 in İstanbul by Mehmet Yılmaz (CEO) and
  Ayşe Demir (co-founder, Ar-Ge Müdürü). B2B SaaS; flagship product NebulaCRM.
- HQ: Büyükdere Caddesi No: 214, Kat 9–11, Maslak, Sarıyer/İstanbul.
- Offices: İstanbul Genel Merkez (Maslak); Ankara Ar-Ge Ofisi (Çankaya, opened Eylül 2019);
  İzmir Müşteri Destek Merkezi (Bayraklı, opened 1 Eylül 2025, shift-based L1 support);
  Berlin sales office = subsidiary Nebula Technology GmbH (Friedrichshain, opened 2 Şubat 2026).
- Headcount: 31.12.2024 = 176; 31.12.2025 = 214; 30.09.2026 = 247
  (İstanbul 158, Ankara 41, İzmir 38, Berlin 10); year-end 2026 target 260.
- Data centres: primary İstanbul `IST-1` (colocation), DR site Ankara `ANK-DR1`;
  EU region `FRA-1` (Frankfurt, opened 1 Temmuz 2026, for DACH customers).
- Board (Yönetim Kurulu, 5): Mehmet Yılmaz (chair & CEO), Ayşe Demir, Dr. Levent Sarıgül
  (independent, chairs the Audit Committee), Hande Okyay (Bosphorus Growth Partners),
  Kaan Ertürk (independent).
- Funding: Series A June 2021, USD 6.5M, led by Kestane Ventures. Series B 14 May 2025,
  USD 28M, led by Bosphorus Growth Partners.
- ESOP pool 8% → board approved 10% on 24 Eylül 2026.
- External auditor for FY2026: Atlas Kuzey Bağımsız Denetim A.Ş. (appointed 24 Eylül 2026).

## People (same names/titles as the demo seeder)

Mehmet Yılmaz (CEO) · Ar-Ge: Ayşe Demir (Ar-Ge Müdürü), Okan Yıldız (Kıdemli Yazılım
Mühendisi), Gizem Aksoy (Veri Bilimci) · BT: Emre Kaya (BT Müdürü), Murat Şen (Sistem
Yöneticisi), Ece Polat (DevOps Mühendisi) · CEO Ofisi: Zeynep Şahin (CEO Ofisi Müdürü),
Kerem Acar (İcra Asistanı) · Finans: Ali Vural (Finans Müdürü), Buse Erdoğan (Mali Müşavir),
Tolga Yıldırım (Finans Analisti) · Hukuk ve Uyum: Elif Aydın (Hukuk ve Uyum Müdürü),
Naz Kurt (Hukuk Müşaviri), Onur Aslan (Uyum Uzmanı) · İK: Burak Çelik (İnsan Kaynakları
Müdürü), Sıla Çetin (İK Uzmanı), Berk Güneş (İşe Alım Uzmanı) · Kalite: Selin Arslan (Kalite
Müdürü), Pınar Yalçın (Kalite Uzmanı), Hakan Bulut (Test Mühendisi) · Müşteri Deneyimi:
Can Öztürk (Müşteri Deneyimi Müdürü), Derya Kılıç (Destek Uzmanı), Efe Taş (Müşteri Başarı
Uzmanı) · Pazarlama ve Satış: Deniz Koç (Pazarlama ve Satış Müdürü), Cansu Aydın (Pazarlama
Uzmanı), Mert Özdemir (Satış Temsilcisi) · Ürün: Merve Doğan (Ürün Müdürü), İrem Korkmaz
(Ürün Sahibi), Yusuf Eren (UX Tasarımcısı).
Other fictional people may appear (external auditors, customer contacts) — invent clearly
fictional names, never real public figures.

## Financials

- FY2024 revenue 298,7 milyon TL; FY2025 revenue 486,3 milyon TL (+%62,8); FY2025 gross
  margin %71,8; FY2025 EBITDA margin %9,4. FY2026 revenue budget 742,0 milyon TL.
- Q3 2026: revenue 198,4 milyon TL; 9M 2026 revenue 536,9 milyon TL vs 9M budget 541,0
  milyon TL (%99,2); Q3 gross margin %73,6; Q3 EBITDA 27,8 milyon TL (%14,0);
  cash 30.09.2026 = 612,5 milyon TL; DSO 47 days (Q2: 52).
- USD view (investor update): ARR 30.09.2026 = $22.4M (31.12.2025: $16.9M; YoY +41%);
  Q3 revenue $4.8M at average 41.3 TRY/USD; cash $14.8M; NRR Q3 2026 = 118%.
- Customers: 31.12.2025 = 1.180; 30.06.2026 = 1.326; 30.09.2026 = 1.412; of which
  Germany 37 (30.09.2026).
- 2026 department OPEX budgets (milyon TL): Ar-Ge 168,4; BT 41,2; Pazarlama ve Satış 96,7;
  Müşteri Deneyimi 38,9; Ürün Yönetimi 22,3; İK 14,6; Finans 9,8; Hukuk ve Uyum 7,4;
  Kalite Yönetimi 6,1; CEO Ofisi 11,5; total 416,9.
- Benefits (2025 → 2026, defined ONLY in the finance budget workbook):
  remote-work allowance (uzaktan çalışma ödeneği, monthly, per eligible employee)
  1.900 → 2.750 TL; meal card (daily) 250 → 330 TL; training budget (annual, per person)
  12.000 → 18.000 TL; sports/health support (monthly) 600 → 900 TL;
  home-office setup support (one-off) 5.000 → 7.500 TL.
- Travel (defined in the travel policy, repeated in the budget assumptions sheet):
  domestic per diem 950 → 1.400 TL/day; abroad per diem 80 → 95 EUR/day;
  hotel cap İstanbul 4.500 TL/night, other cities 3.200 TL/night (2026); mileage 9,5 TL/km.
- Purchasing approval matrix: ≤25.000 TL department head; 25.001–250.000 TL Finans Müdürü
  (Ali Vural); 250.001–1.000.000 TL CEO (Mehmet Yılmaz); >1.000.000 TL Yönetim Kurulu.
  ≥100.000 TL needs at least 3 written quotes; ≥500.000 TL goes to the Satın Alma Komitesi.
  Standard supplier payment term 45 days.

## Products & pricing

- NebulaCRM tiers (2026 list, effective 1 Ocak 2026, per user per month, KDV hariç):
  Başlangıç 690 TL (3–25 users) · Profesyonel 1.290 TL (min 5) · Kurumsal 2.150 TL (min 25)
  · Kurumsal Plus "3.400 TL'den başlayan" custom quote (min 100).
  Annual prepay discount %15; 2-year prepay %22.
  EUR list (DACH): Starter €24, Professional €45, Enterprise €75, Enterprise Plus from €119.
- 2025 list (archived, 1 Ocak–31 Aralık 2025): Başlangıç 520 TL, Profesyonel 990 TL,
  Kurumsal 1.650 TL, Kurumsal Plus from 2.600 TL; annual prepay discount %12.
- Add-ons 2026: NebulaAnalytics 390 TL/user/month (2025: 290 TL); Nebula Assist for
  Profesyonel 240 TL/user/month (included in Kurumsal and Kurumsal Plus).
- Discount authority (direct sales, 2026): ≤%10 sales rep; ≤%25 Deniz Koç (Pazarlama ve Satış
  Müdürü); >%25 CEO approval.
- Versions: v3.2 GA 10 Şubat 2026; v3.3 GA 12 Mayıs 2026; v3.4 GA 15 Eylül 2026;
  v3.5 planned 8 Aralık 2026; v4.0 planned Q2 2027. API v2 sunset 31 Mart 2027.
- v3.3 raised the Profesyonel API rate limit from 200 to 300 requests/minute and bulk import
  from 10.000 to 50.000 rows. v3.4 raised bulk import to 100.000 rows, made Nebula Assist GA,
  added FRA-1 tenant migration, and rebuilt report export (1 million rows in under 90 seconds).
- API v3 rate limits per token: Starter 60 rpm, Professional 300 rpm, Enterprise 1,200 rpm,
  Enterprise Plus 3,000 rpm. Base URL `https://api.nebulacrm.example/v3`.
- Nebula Assist (AI assistant): beta 1 Temmuz 2026 with 40 pilot customers; GA with v3.4 on
  15 Eylül 2026; monthly quota 500 requests/user (Kurumsal), 1.500 (Kurumsal Plus);
  p95 latency target < 4 s; answers must cite CRM records; customer data is never used for
  model training; inference sub-processor Terra LLM Hizmetleri A.Ş. (hosted in Türkiye).

## Support & SLA (2026)

First-response targets:

| Plan | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| Başlangıç | 8 iş saati | 2 iş günü | 3 iş günü | 5 iş günü |
| Profesyonel | 2 saat | 8 iş saati | 2 iş günü | 5 iş günü |
| Kurumsal | 30 dakika | 4 saat | 1 iş günü | 3 iş günü |
| Kurumsal Plus | 15 dakika | 2 saat | 8 iş saati | 2 iş günü |

Uptime commitment: Başlangıç none (target 99,5), Profesyonel 99,5, Kurumsal 99,9,
Kurumsal Plus 99,95. Service credits (Kurumsal & Kurumsal Plus): monthly uptime
<99,9 and ≥99,0 → %10; <99,0 and ≥95,0 → %25; <95,0 → %50. Profesyonel: below 99,5 → %10.
Credits must be requested within 30 days. Kurumsal Plus gets a named TAM.
Support channels: destek@nebulacrm.example, phone, in-app chat; L1 İzmir, L2 product
specialists, L3 Ar-Ge on-call.
Customer metrics: NPS 2025 = 41; Q1 2026 = 42; Q2 2026 = 46; Q3 2026 = 44.
CSAT Q2 %91,1, Q3 %92,4. Tickets Q2 17.205, Q3 18.640. Median first response Q3 38 dakika.
Top Q3 complaint: report export performance (fixed in v3.4).
Churn: 2025 gross logo churn 7,8%; H1 2026 annualised 6,9% (41 logos lost in H1 2026).

## Security, operations, quality

- Password policy v2.0 (2026, effective 1 Mart 2026, owner Emre Kaya): min 14 characters;
  no periodic rotation (change only on suspicion); MFA everywhere (FIDO2 keys for admins);
  lockout after 10 failed attempts for 15 minutes; history 12; service-account secrets
  rotate every 180 days; privileged access reviewed quarterly.
  Superseded v1.3 (2025, effective 15 Ocak 2025, retired 1 Mart 2026): min 12 characters;
  rotation every 90 days; lockout after 5 attempts for 30 minutes; history 5; MFA only for
  VPN and e-mail.
- Backup/DR: continuous WAL archiving; RPO 15 dakika; RTO 4 saat (Kurumsal Plus 2 saat);
  daily snapshot 02:00; retention 35 days daily + 12 monthly; DR tests twice a year —
  last 23 Mayıs 2026 (achieved RTO 2 saat 41 dakika), next 21 Kasım 2026; DR test records
  are signed off by Emre Kaya.
- Incidents: INC-2025-1107 (7 Kasım 2025, 52 minutes, Sev-2, DNS change on load balancer).
  INC-2026-0417 (17 April 2026, 09:12–11:59 TRT = 167 minutes, Sev-1): WAL archiving stalled
  after an object-storage credential rotation, primary DB disk filled, DB went read-only;
  38% of API requests failed; 286 customer accounts affected; April uptime 99.61%;
  service credits TRY 1.24M to 61 Kurumsal/Kurumsal Plus customers; incident commander
  Ece Polat; WAL-lag alert action owned by Murat Şen (due 15 May 2026).
- ISO/IEC 27001:2022 surveillance audit 9–11 Haziran 2026 by Certa Belgelendirme A.Ş.
  (lead auditor Nihat Karaca): 0 major, 3 minor non-conformities, 4 observations; minor NC-3:
  DR test record lacked sign-off; corrective actions due 9 Eylül 2026; certificate valid to
  27 Haziran 2027.
- Release quality gate: new-code coverage ≥%80; 0 open P1/P2 defects; p95 regression ≤%10;
  no critical/high security findings; release train every 2 weeks on Tuesday; freeze
  15 Aralık–5 Ocak; Go/No-Go chaired by Selin Arslan.
- Load test Q2 2026: 3,000 RPS sustained → p95 212 ms; breaking point 4,150 RPS;
  2025 baseline p95 268 ms at 2,000 RPS; recommends 2 extra DB replicas (est. TRY 840,000).

## HR

- Remote/hybrid policy 2026: core office days Salı and Perşembe; allowance eligibility =
  on average ≥2 remote days per week; amounts are NOT in the HR policy — it points to the
  finance budget workbook ("Yan Haklar ve Ödenekler" sheet). Work from abroad ≤20 iş günü/yıl.
  Core hours 10:00–16:00. Not applicable to İzmir shift staff.
- Leave: statutory 14/20/26 days + 2 days "Nebula ek izni"; birthday leave 1 day;
  marriage 5 days; paternity 10 days; carry-over max 10 days, use by 31 Mart.
- Performance: rating multipliers 5 → %150, 4 → %120, 3 → %100, 2 → %50, 1 → %0; target
  bonus L1–L2 %8, L3–L4 %12, L5 (manager) %18, director %25; company factor 2025 = 0,92;
  bonus paid in March.
- Hiring: referral bonus 40.000 TL engineering / 20.000 TL other, paid after the 2-month
  probation; time-to-hire target 35 days.

## Legal

- KVKK retention: tenant CRM data deleted 90 days after contract end; backups roll off in
  35 days; access logs 2 years; job-applicant CVs 1 year; contracts 10 years; periodic
  destruction every 6 months (Haziran, Aralık); breach notification to the Kurul within
  72 hours; contact kvkk@nebulacrm.example, liaison Onur Aslan.
- DPA (customer-facing, English): breach notice to customer within 48 hours; sub-processor
  change notice 30 days, objection window 14 days; one audit per 12 months.
- Sub-processors: Kumulus Bulut Hizmetleri A.Ş. (IST-1 colocation), Anka Veri Merkezleri A.Ş.
  (ANK-DR1), Rheinwerk Hosting GmbH (FRA-1), Terra LLM Hizmetleri A.Ş. (Nebula Assist
  inference), PostaGüvercini İleti A.Ş. (transactional e-mail), Lyra Mesaj A.Ş. (SMS OTP),
  Nebula Technology GmbH (affiliate, DACH support).
- Ethics: gift/hospitality limit 2.000 TL (2025: 1.500 TL); ethics line etik@nebulacrm.example;
  investigations closed within 45 days; committee chaired by Elif Aydın.

## Strategy

- 2026–2028 targets: ARR $50M by end-2028; international revenue %25 by 2028 (2026: %6);
  headcount 400 by 2028; EBITDA margin %20 by 2028. Markets: DACH (2026), Gulf with a Dubai
  office planned for 2027 H2.
- Board meeting 2026/05 (24 Eylül 2026): Dubai market research budget 3,5 milyon TL;
  2027 budget framework revenue growth target %45; ESOP 8% → 10%; auditor appointment;
  next meeting 10 Aralık 2026. Previous meeting 2026/04 (25 Haziran 2026) capped Berlin
  headcount at 12.

## Document inventory (39 documents)

Which document *owns* which facts. A fact owned by one document may be repeated
elsewhere only where this list says so (cross-links), so multi-hop questions have a
single authoritative source per hop. Near-miss distractors are deliberate.

| # | File | Fmt | Lang | Owns / must state | Distractors & cross-links |
|---|---|---|---|---|---|
| 1 | arge/Teknik_Mimari_NebulaCRM_2026.pdf | PDF | tr | 34 microservices (Go core, TypeScript web), PostgreSQL 16 primary + 2 replicas, Redis 7, Kafka (3 brokers), Kubernetes 1.30, envs dev/staging/prod, tenant isolation via tenant_id + row-level security, dedicated DB option for Kurumsal Plus, peak 2.400 RPS (Eylül 2026), IST-1/ANK-DR1/FRA-1 | owner Ayşe Demir; mentions FRA-1 opened 1 Temmuz 2026 |
| 2 | arge/Load_Test_Report_2026_Q2.docx | DOCX | en | 2–6 June 2026; 3,000 RPS → p95 212 ms, p99 480 ms, errors 0.04%; breaking point 4,150 RPS (DB CPU 92%); recommends 2 extra DB replicas, est. TRY 840,000 | 2025 baseline p95 268 ms @ 2,000 RPS; authors Hakan Bulut, Okan Yıldız |
| 3 | arge/NebulaCRM_API_v3_Reference.md | MD | en | base URL, API keys `ncrm_live_` + 32 hex, rate limits per plan, 429 + Retry-After, cursor pagination default 50 max 200, webhooks HMAC-SHA256 `X-Nebula-Signature`, 6 retries over ~24 h, `Idempotency-Key`, v2 sunset 31 March 2027 | Professional 300 rpm (v3.3 notes say it was 200 before) |
| 4 | arge/Engineering_Code_Review_Guidelines.txt | TXT | en | 2 approvals for critical paths (billing, auth, tenancy), else 1; PR soft limit 400 changed lines; branch `feature/NCRM-1234-short-desc`; squash merge; first review within 1 business day; release train every 2 weeks on Tuesday; hotfix rules | release cadence also in #6 |
| 5 | kalite-yonetimi/ISO_27001_Gozetim_Denetimi_Raporu_2026.pdf | PDF | tr | audit 9–11 Haziran 2026, Certa Belgelendirme A.Ş., lead auditor Nihat Karaca, 0 major / 3 minor / 4 observations, minor NC list (NC-3 = DR test record unsigned), corrective actions due 9 Eylül 2026, cert valid to 27 Haziran 2027 | NC-3 links to #11 (who signs DR records) |
| 6 | kalite-yonetimi/Release_Kalite_Kapisi_Proseduru.docx | DOCX | tr | quality gate thresholds, Go/No-Go chaired by Selin Arslan, freeze 15 Aralık–5 Ocak | p95 regression ≤%10 |
| 7 | kalite-yonetimi/Kalite_Metrikleri_2026_Q3.txt | TXT | tr | Q3 2026 quality KPIs (escaped defects 14, change failure rate %4,1, deploys/day 3,6, MTTR Sev-1/2 1 saat 12 dakika, automated tests 18.420, flaky %1,3) | Q2 values alongside (escaped defects 22, CFR %5,8 …) |
| 8 | bilgi-teknolojileri/Parola_ve_Erisim_Politikasi_v2.0_2026.pdf | PDF | tr | password policy v2.0 | change table vs v1.3 |
| 9 | bilgi-teknolojileri/Parola_Politikasi_v1.3_2025_ARSIV.txt | TXT | tr | password policy v1.3, clearly marked superseded on 1 Mart 2026 | distractor for #8 |
| 10 | bilgi-teknolojileri/BT_Varlik_Envanteri_2026.xlsx | XLSX | tr | laptops 262 (NB-14P 148, NB-16X 71, NB-13L 43), monitors 318, servers IST-1 46 / ANK-DR1 18 / FRA-1 12, refresh cycle 4 years, asset rows with tags and assignees | as of 30.09.2026 |
| 11 | bilgi-teknolojileri/Yedekleme_ve_Felaket_Kurtarma_Plani.docx | DOCX | tr | RPO/RTO, snapshot 02:00, retention, DR test dates/results, sign-off by Emre Kaya | links to #5 and #12 |
| 12 | bilgi-teknolojileri/Postmortem_INC-2026-0417_Database_Outage.pdf | PDF | en | INC-2026-0417 timeline, 167 min, 38%, 286 accounts, April uptime 99.61%, credits TRY 1.24M to 61 customers, IC Ece Polat, action items with owners/dates | mentions INC-2025-1107 (52 min) as prior incident; credit % comes from #25 |
| 13 | hukuk-uyum/KVKK_Kisisel_Veri_Saklama_ve_Imha_Politikasi.pdf | PDF | tr | retention table, destruction every 6 months, 72 h to Kurul, kvkk@ contact, Onur Aslan | 90-day tenant deletion also in #14 |
| 14 | hukuk-uyum/Data_Processing_Agreement_Template_v2026.docx | DOCX | en | 48 h customer breach notice, 30-day sub-processor notice, 14-day objection, audit 1×/12 months, data locations | 48 h vs 72 h (#13) |
| 15 | hukuk-uyum/Subprocessor_Register_2026.xlsx | XLSX | en | sub-processor rows: name, service, location, data categories, since | Terra LLM ↔ Nebula Assist (#31), Rheinwerk ↔ FRA-1 |
| 16 | hukuk-uyum/Etik_Kurallar_ve_Ihbar_Proseduru.md | MD | tr | gift limit 2.000 TL (2025: 1.500 TL), ethics line, 45 days, committee | |
| 17 | finans/Butce_ve_Gider_Plani_2026.xlsx | XLSX | tr | department OPEX, revenue budget, benefits sheet "Yan Haklar ve Ödenekler" (2025 vs 2026), travel assumptions | the ONLY source of allowance amounts (#21 points here) |
| 18 | finans/Satin_Alma_ve_Onay_Yetkileri_Proseduru.docx | DOCX | tr | approval matrix, 3 quotes ≥100.000 TL, committee ≥500.000 TL, 45-day payment term, supplier KVKK questionnaire | used with #2 (TRY 840,000 → CEO) |
| 19 | finans/Seyahat_ve_Harcama_Politikasi_2026.pdf | PDF | tr | per diem, hotel caps, flights, 30/60-day expense rules, mileage | 2025 values in a change table |
| 20 | finans/Finansal_Sonuclar_2026_Q3.pdf | PDF | tr | Q3 & 9M results in TL, DSO, cash | Q2 comparatives |
| 21 | insan-kaynaklari/Uzaktan_ve_Hibrit_Calisma_Politikasi_2026.docx | DOCX | tr | core days, eligibility, abroad limit, core hours, İzmir exclusion; refers to #17 for amounts | multi-hop with #17 |
| 22 | insan-kaynaklari/Izin_Yonetmeligi_2026.pdf | PDF | tr | leave entitlements, carry-over, request lead time | |
| 23 | insan-kaynaklari/Performans_Degerlendirme_ve_Prim_Sistemi.pdf | PDF | tr | cycles, rating multipliers, target bonus %, company factor 0,92 | |
| 24 | insan-kaynaklari/Ise_Alim_ve_Oryantasyon_Rehberi.md | MD | tr | stages, referral bonus, probation, 35 days, onboarding | |
| 25 | musteri-deneyimi/Destek_SLA_Matrisi_2026.xlsx | XLSX | tr | first-response matrix, uptime, service-credit tiers, support hours | used with #12 |
| 26 | musteri-deneyimi/Musteri_Destek_El_Kitabi.md | MD | tr | channels, priority definitions, L1/L2/L3, escalation, auto-close | |
| 27 | musteri-deneyimi/Musteri_Memnuniyeti_Raporu_2026_Q3.pdf | PDF | tr | NPS/CSAT/tickets Q3 with Q1/Q2 comparatives, top complaint | links to #30 (export fix) |
| 28 | musteri-deneyimi/Churn_Analysis_H1_2026.docx | DOCX | en | H1 2026 churn, reasons %, save desk | 2025 churn 7.8% |
| 29 | urun-yonetimi/Surum_Notlari_NebulaCRM_v3.3.md | MD | tr | v3.3 features, API limit 200→300, import 10.000→50.000 | distractor for #30 |
| 30 | urun-yonetimi/Release_Notes_NebulaCRM_v3.4.md | MD | en | v3.4 features, import 100,000, Assist GA, export 1M rows < 90 s, FRA-1 migration | |
| 31 | urun-yonetimi/PRD_Nebula_Assist.docx | DOCX | tr | goals, quotas, p95 < 4 s, beta/GA dates, no-training rule | |
| 32 | pazarlama-satis/Fiyat_Listesi_2026.xlsx | XLSX | tr | 2026 tier prices, EUR list, add-ons, prepay discounts, discount authority | |
| 33 | pazarlama-satis/Fiyat_Listesi_2025_ARSIV.pdf | PDF | tr | 2025 prices, marked archived | distractor for #32 |
| 34 | pazarlama-satis/Satis_Performansi_2026_Q3.pptx | PPTX | tr | Q3 sales KPIs (new ARR $2.1M, 112 new logos, win rate %27 vs Q2 %24, cycle 64 days, pipeline $9.8M, quota attainment %103), Lodos Lojistik +1.100 seats with %28 discount | discount → #32 authority (CEO) |
| 35 | pazarlama-satis/Partner_Program_Guide_2026.md | MD | en | partner tiers, margins, requirements, deal registration 90 days | |
| 36 | ceo-ofisi/Investor_Update_Q3_2026.pdf | PDF | en | USD KPIs, highlights/lowlights | |
| 37 | ceo-ofisi/Yonetim_Kurulu_Toplanti_Tutanagi_2026-05.docx | DOCX | tr | board meeting 2026/05 decisions | refers to 2026/04 decisions |
| 38 | ceo-ofisi/Stratejik_Plan_2026_2028.pptx | PPTX | tr | strategy targets, Dubai 2027 H2 | |
| 39 | ceo-ofisi/Genelge_Maslak_10_Kat_Tadilati.png | PNG | tr | scanned memo: 10th-floor renovation 14–18 Aralık 2026, access cards by 27 Kasım 2026, contact Kerem Acar ext. 1042, ref CEO-2026-031 | OCR |
