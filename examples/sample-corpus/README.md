# Sample corpus (synthetic)

Every document in this folder is **synthetic and fictional**. It describes an
imaginary company, "Nebula Teknoloji A.Ş.", and its imaginary products
(NebulaCRM, NebulaAnalytics, Nebula Assist). All people, customers, partners,
suppliers, auditors and investors are invented; e-mail addresses and URLs use
the reserved `.example` domain (RFC 2606). Any resemblance to real companies,
products or people is coincidental. The files contain no personal data.

The corpus exists to demo and benchmark Raggie end to end. Unlike a pile of
boilerplate, every document carries specific, checkable facts (amounts, dates,
thresholds, owners, table values) that the exact-answer golden set in
[`examples/golden/golden.yaml`](../golden/golden.yaml) asks about.

## The company

Nebula Teknoloji is a B2B SaaS company founded in 2014 in İstanbul (HQ in
Maslak), with an R&D office in Ankara, a support centre in İzmir and a sales
subsidiary in Berlin — 247 employees and 1,412 paying customers at
30 September 2026. Its CRM is sold in four tiers (Başlangıç, Profesyonel,
Kurumsal, Kurumsal Plus) and runs in three data centres (İstanbul IST-1, Ankara
ANK-DR1, Frankfurt FRA-1). The documents span 2025–2026: policies and their
superseded versions, a budget, quarterly results, an investor update, board
minutes, a production outage postmortem, an ISO 27001 audit, release notes,
price lists, an SLA matrix and more. People and titles match the demo users
that `make demo` creates. The full fact sheet the documents agree on is
[`scripts/corpus/WORLD.md`](../../scripts/corpus/WORLD.md).

The documents are written to exercise real retrieval problems:

- **Cross-document links** for multi-hop questions (e.g. the remote-work policy
  defers the allowance amount to the finance budget workbook; the postmortem's
  April uptime maps to a service-credit tier in the SLA matrix).
- **Near-miss distractors** for precision (2025 vs 2026 price lists, password
  policy v1.3 vs v2.0, v3.3 vs v3.4 release notes, previous-quarter columns).
- **Mixed formats and languages**: tables in PDF/DOCX/XLSX, slide decks with
  speaker notes, a scanned memo that only OCR can read, ~25% English documents.

## Contents (39 documents, ~1.6 MB)

| Folder (workspace) | Documents |
|---|---|
| `arge` (Ar-Ge) | Teknik_Mimari_NebulaCRM_2026.pdf · Load_Test_Report_2026_Q2.docx (EN) · NebulaCRM_API_v3_Reference.md (EN) · Engineering_Code_Review_Guidelines.txt (EN) |
| `bilgi-teknolojileri` (BT) | Parola_ve_Erisim_Politikasi_v2.0_2026.pdf · Parola_Politikasi_v1.3_2025_ARSIV.txt · BT_Varlik_Envanteri_2026.xlsx · Yedekleme_ve_Felaket_Kurtarma_Plani.docx · Postmortem_INC-2026-0417_Database_Outage.pdf (EN) |
| `ceo-ofisi` | Investor_Update_Q3_2026.pdf (EN) · Yonetim_Kurulu_Toplanti_Tutanagi_2026-05.docx · Stratejik_Plan_2026_2028.pptx · Genelge_Maslak_10_Kat_Tadilati.png (scanned memo) |
| `finans` | Butce_ve_Gider_Plani_2026.xlsx · Satin_Alma_ve_Onay_Yetkileri_Proseduru.docx · Seyahat_ve_Harcama_Politikasi_2026.pdf · Finansal_Sonuclar_2026_Q3.pdf |
| `hukuk-uyum` | KVKK_Kisisel_Veri_Saklama_ve_Imha_Politikasi.pdf · Data_Processing_Agreement_Template_v2026.docx (EN) · Subprocessor_Register_2026.xlsx (EN) · Etik_Kurallar_ve_Ihbar_Proseduru.md |
| `insan-kaynaklari` | Uzaktan_ve_Hibrit_Calisma_Politikasi_2026.docx · Izin_Yonetmeligi_2026.pdf · Performans_Degerlendirme_ve_Prim_Sistemi.pdf · Ise_Alim_ve_Oryantasyon_Rehberi.md |
| `kalite-yonetimi` | ISO_27001_Gozetim_Denetimi_Raporu_2026.pdf · Release_Kalite_Kapisi_Proseduru.docx · Kalite_Metrikleri_2026_Q3.txt |
| `musteri-deneyimi` | Destek_SLA_Matrisi_2026.xlsx · Musteri_Destek_El_Kitabi.md · Musteri_Memnuniyeti_Raporu_2026_Q3.pdf · Churn_Analysis_H1_2026.docx (EN) |
| `pazarlama-satis` | Fiyat_Listesi_2026.xlsx · Fiyat_Listesi_2025_ARSIV.pdf · Satis_Performansi_2026_Q3.pptx · Partner_Program_Guide_2026.md (EN) |
| `urun-yonetimi` | Surum_Notlari_NebulaCRM_v3.3.md · Release_Notes_NebulaCRM_v3.4.md (EN) · PRD_Nebula_Assist.docx |

By format: 12 PDF (real text layer), 9 DOCX, 5 XLSX, 2 PPTX, 7 Markdown,
3 plain text, 1 PNG (OCR). By language: 29 Turkish, 10 English.

## Loading it

```bash
make demo
```

The demo seeder maps each folder to a department workspace (plus a company-wide
workspace holding everything) and uploads the files through the normal intake
path, so the ingestion workers index them like any user upload.

## Regenerating

The files are generated, not hand-edited. Content lives in
`scripts/corpus/content/<folder>.py`; the build is deterministic (fixed
creation dates, no author metadata, fixed ZIP timestamps), so a rebuild is
byte-identical:

```bash
uv run scripts/corpus/build.py --clean   # regenerate this folder
uv run scripts/corpus/validate.py        # check the golden set against it
```

## License

The sample corpus and its golden set are dedicated to the public domain under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Use them freely,
including for benchmarking other RAG systems.
