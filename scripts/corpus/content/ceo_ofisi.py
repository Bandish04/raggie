# SPDX-License-Identifier: Apache-2.0

"""CEO Ofisi: Q3 investor update, board minutes 2026/05, 2026–2028 strategy deck,
scanned memo on the Maslak 10th-floor renovation (OCR)."""

from model import H1, H2, OL, UL, D, Doc, P, Slide, T

INVESTOR_UPDATE = Doc(
    path="ceo-ofisi/Investor_Update_Q3_2026.pdf",
    title="Investor Update — Q3 2026",
    subtitle="Quarterly letter to the shareholders of Nebula Teknoloji A.Ş.",
    lang="en",
    date=D(2026, 10, 22),
    doc_no="CEO-IR-2026-Q3",
    classification="Confidential — shareholders only",
    meta=(
        ("From", "Mehmet Yılmaz, CEO and Chairman of the Board"),
        ("Prepared with", "Ali Vural (Finance), Zeynep Şahin (CEO Office)"),
        ("Reporting period", "1 July – 30 September 2026"),
    ),
    blocks=(
        H1("Dear shareholders,"),
        P(
            "Q3 2026 was the quarter in which two long-running bets went live: Nebula Assist, our "
            "AI assistant inside NebulaCRM, reached general availability on 15 September 2026 with "
            "release v3.4, and our EU region FRA-1 in Frankfurt opened on 1 July 2026, giving our "
            "German-speaking customers in-region hosting for the first time. Commercially it was "
            "our strongest quarter to date, and for the third quarter in a row we were EBITDA "
            "positive on a reported basis."
        ),
        P(
            "All figures in this letter are unaudited management numbers. Turkish lira amounts are "
            "translated at the Q3 average rate of 41.3 TRY/USD unless stated otherwise; balance "
            "sheet items use the 30 September 2026 closing rate of 41.4 TRY/USD."
        ),
        H1("1. Q3 2026 at a glance"),
        T(
            ("Metric", "Q2 2026", "Q3 2026", "Change"),
            (
                ("ARR (end of period)", "$20.3M", "$22.4M", "+10% QoQ"),
                ("Revenue (quarter)", "$4.4M", "$4.8M", "+9% QoQ"),
                ("Net revenue retention", "115%", "118%", "+3 pts"),
                ("Gross margin", "72.4%", "73.6%", "+1.2 pts"),
                ("EBITDA margin", "12.1%", "14.0%", "+1.9 pts"),
                ("Paying customers", "1,326", "1,412", "+86"),
                ("Customers in Germany", "28", "37", "+9"),
                ("Headcount", "236", "247", "+11"),
                ("Cash (end of period)", "$14.1M", "$14.8M", "+$0.7M"),
            ),
            caption="Table 1. Key performance indicators. ARR at 31 December 2025 was $16.9M, so "
            "ARR has grown 41% year over year.",
            widths=(2.4, 1.2, 1.2, 1.2),
        ),
        P(
            "In lira terms, Q3 revenue was TRY 198.4M and nine-month revenue TRY 536.9M, which is "
            "99.2% of the nine-month budget. Cash on hand at quarter end was TRY 612.5M; we have "
            "not drawn on the Series B proceeds for operating expenses since February 2026."
        ),
        H1("2. Highlights"),
        H2("Nebula Assist is generally available"),
        P(
            "Nebula Assist left beta on 15 September 2026 after a ten-week pilot with 40 customers. "
            "It is included in the Kurumsal and Kurumsal Plus plans and sold as an add-on on "
            "Profesyonel. In the first two weeks after GA, 173 tenants switched it on and 31 "
            "Profesyonel customers bought the add-on. Every answer cites the CRM records it used "
            "and customer data is never used for model training — a point that has mattered in "
            "every enterprise security review so far."
        ),
        H2("International: DACH is working"),
        P(
            "The Berlin office (Nebula Technology GmbH) opened on 2 February 2026 and now has 10 "
            "employees. Germany ended the quarter with 37 paying customers, up from 28 at the end of "
            "Q2; nine of the 112 new logos we signed in Q3 were German. Since FRA-1 opened, every "
            "new DACH customer has chosen EU hosting, and the self-service migration tool shipped "
            "in v3.4 lets existing tenants move with at most 30 minutes of read-only time."
        ),
        H2("Sales execution"),
        UL(
            "New ARR of $2.1M in Q3 against a quota of $2.04M (103% attainment).",
            "112 new logos; win rate improved to 27% from 24% in Q2.",
            "Average sales cycle of 64 days; qualified pipeline of $9.8M entering Q4.",
            "Largest deal: Lodos Lojistik A.Ş. expanded by 1,100 seats to 3,500 seats on a "
            "three-year Kurumsal Plus agreement.",
        ),
        H1("3. Lowlights and what we are doing about them"),
        P(
            "Reliability. The April database outage (INC-2026-0417, 167 minutes, 286 customer "
            "accounts affected) still shapes our year. We paid TRY 1.24M in service credits to 61 "
            "Kurumsal and Kurumsal Plus customers, booked against Q2 revenue. All six postmortem "
            "actions except the quarterly failover game day are complete; at the board's request, "
            "the Audit Committee now reviews failover test results every quarter."
        ),
        P(
            "Customer sentiment. NPS slipped from 46 in Q2 to 44 in Q3. The single largest driver "
            "was report export performance on large accounts. The export pipeline was rebuilt in "
            "v3.4 and now exports one million rows in under 90 seconds; we expect to see the effect "
            "in the Q4 survey."
        ),
        P(
            "Hiring. We ended Q3 at 247 people against a plan of 252, mostly due to slower senior "
            "engineering hiring in Ankara. We still expect to finish the year close to the budgeted "
            "260."
        ),
        H1("4. Outlook for Q4 2026"),
        UL(
            "Full-year 2026 revenue forecast: TRY 738.5M against a budget of TRY 742.0M.",
            "Exit ARR target for 2026: $25.0M, unchanged from the strategic plan.",
            "NebulaCRM v3.5 is scheduled for 8 December 2026, ahead of the year-end release freeze.",
            "2027 budget to be presented at the board meeting on 10 December 2026, prepared "
            "under a 45% revenue growth framework.",
        ),
        H1("5. Governance"),
        P(
            "At the board meeting of 24 September 2026 the board approved a TRY 3.5M market "
            "research budget for a possible Dubai office, expanded the employee stock option pool "
            "from 8% to 10% of fully diluted shares, and appointed Atlas Kuzey Bağımsız Denetim A.Ş. as "
            "external auditor for the 2026 financial year. Minutes are available to shareholders on "
            "request from the CEO Office."
        ),
        H1("6. How you can help"),
        UL(
            "Introductions to logistics and insurance companies in Germany and Austria with 200 or "
            "more CRM users.",
            "Referrals for a Head of Sales DACH based in Berlin.",
            "Feedback on our Gulf market thesis before the Dubai research kicks off in January "
            "2027.",
        ),
        P(
            "Our next update will follow the year-end close, in the last week of January 2027. "
            "As always, thank you for your support — questions are welcome at "
            "investors@nebulacrm.example."
        ),
        P("Mehmet Yılmaz, CEO"),
    ),
)

BOARD_MINUTES = Doc(
    path="ceo-ofisi/Yonetim_Kurulu_Toplanti_Tutanagi_2026-05.docx",
    title="Yönetim Kurulu Toplantı Tutanağı — 2026/05",
    subtitle="Nebula Teknoloji A.Ş. Yönetim Kurulu olağan toplantısı",
    lang="tr",
    date=D(2026, 9, 24),
    doc_no="YK-2026/05",
    classification="Gizli",
    meta=(
        ("Toplantı tarihi ve saati", "24 Eylül 2026, 14:00–17:20"),
        ("Yer", "Genel Merkez, Maslak, 11. kat Yönetim Kurulu salonu"),
        ("Raportör", "Zeynep Şahin, CEO Ofisi Müdürü"),
    ),
    blocks=(
        H1("1. Katılımcılar ve toplantı nisabı"),
        P(
            "Yönetim Kurulu üyeleri: Mehmet Yılmaz (Yönetim Kurulu Başkanı ve CEO), Ayşe Demir, "
            "Dr. Levent Sarıgül (bağımsız üye, Denetim Komitesi Başkanı), Hande Okyay (Bosphorus "
            "Growth Partners temsilcisi) ve Kaan Ertürk (bağımsız üye). Beş üyenin tamamı hazır "
            "bulunmuş, toplantı ve karar nisabı sağlanmıştır. Kaan Ertürk toplantıya video "
            "konferans ile katılmıştır."
        ),
        P(
            "Davetliler: Ali Vural (Finans Müdürü, 2. ve 3. gündem maddeleri), Elif Aydın (Hukuk ve "
            "Uyum Müdürü, 5. ve 6. gündem maddeleri), Deniz Koç (Pazarlama ve Satış Müdürü, 4. "
            "gündem maddesi). Davetliler oy hakkına sahip değildir."
        ),
        H1("2. Gündem"),
        OL(
            "Önceki toplantı (2026/04) tutanağının onayı ve karar takibi",
            "2026 üçüncü çeyrek ön finansal sonuçları",
            "2027 bütçe hazırlık çerçevesi",
            "Körfez pazarı (Dubai) pazar araştırması",
            "Çalışan pay opsiyon havuzunun genişletilmesi",
            "2026 hesap dönemi için bağımsız denetçi seçimi",
            "INC-2026-0417 sonrası operasyonel dayanıklılık ve ISO/IEC 27001 bulguları",
            "Dilekler ve bir sonraki toplantı tarihi",
        ),
        H1("3. Görüşmeler"),
        H2("3.1 Önceki toplantı kararlarının takibi"),
        P(
            "25 Haziran 2026 tarihli 2026/04 sayılı toplantının tutanağı okunarak oybirliğiyle "
            "onaylandı. Karar takibinde şu hususlar not edildi: 2026/04-3 sayılı kararla Berlin "
            "ofisi (Nebula Technology GmbH) için 2026 sonuna kadar en fazla 12 kişilik kadro tavanı "
            "belirlenmişti; 30 Eylül 2026 itibarıyla Berlin'de 10 çalışan bulunmaktadır. 2026/04-5 "
            "sayılı kararla Dubai için ayrılan 750.000 TL'lik ön fizibilite çalışması tamamlanmış ve "
            "rapor üyelere dağıtılmıştır."
        ),
        H2("3.2 Üçüncü çeyrek ön sonuçları"),
        P(
            "Ali Vural, 2026 üçüncü çeyrek gelirinin 198,4 milyon TL, dokuz aylık gelirin 536,9 "
            "milyon TL olduğunu ve dokuz aylık bütçenin %99,2 oranında gerçekleştiğini sundu. "
            "Üçüncü çeyrek FAVÖK marjı %14,0, 30 Eylül 2026 itibarıyla nakit mevcudu 612,5 milyon "
            "TL'dir. Yıl sonu gelir tahmini 738,5 milyon TL olarak paylaşıldı. Hande Okyay, tahsilat "
            "süresindeki iyileşmeyi (ortalama tahsilat süresinin 52 günden 47 güne inmesi) olumlu "
            "karşıladığını belirtti."
        ),
        H2("3.3 2027 bütçe çerçevesi"),
        P(
            "CEO, 2027 bütçesinin %45 gelir büyümesi ve en az %16 FAVÖK marjı varsayımlarıyla "
            "hazırlanmasını önerdi. Dr. Levent Sarıgül, kur varsayımının üç senaryolu (baz, "
            "olumsuz, çok olumsuz) olarak sunulmasını istedi. Bütçe taslağının 10 Aralık 2026 "
            "toplantısında onaya sunulmasına karar verildi."
        ),
        H2("3.4 Dubai pazar araştırması"),
        P(
            "Deniz Koç, ön fizibilite bulgularını sundu: Körfez'de NebulaCRM kullanan 6 müşteri "
            "bulunmakta, Arapça arayüz ve yerel veri barındırma talebi öne çıkmaktadır. Stratejik "
            "plandaki 2027 ikinci yarı Dubai ofisi hedefine hazırlık olarak kapsamlı pazar "
            "araştırması için 3,5 milyon TL bütçe talep edildi. Araştırmanın proje sahibi Deniz Koç "
            "olacak, sonuç raporu en geç 31 Mart 2027'de Yönetim Kurulu'na sunulacaktır."
        ),
        H2("3.5 Pay opsiyon havuzu"),
        P(
            "Elif Aydın, çalışan pay opsiyon havuzunun tam seyreltilmiş sermayenin %8'inden %10'una "
            "çıkarılmasına ilişkin hukuki çerçeveyi sundu. Yeni tahsislerde hak kazanım süresi 4 "
            "yıl, ilk hak kazanım eşiği 1 yıl olarak korunacaktır. Kaan Ertürk, kıdemli mühendis "
            "tahsislerinin performans koşuluna bağlanmasını önerdi; öneri bir sonraki toplantıda "
            "ayrıca görüşülecektir."
        ),
        H2("3.6 Bağımsız denetçi seçimi"),
        P(
            "Denetim Komitesi, üç teklif arasından Atlas Kuzey Bağımsız Denetim A.Ş.'yi önerdi. Önerilen "
            "denetim ücreti 2026 hesap dönemi için 1,85 milyon TL'dir (KDV hariç)."
        ),
        H2("3.7 Operasyonel dayanıklılık"),
        P(
            "Ayşe Demir, 17 Nisan 2026'daki INC-2026-0417 kesintisinin aksiyonlarını özetledi: altı "
            "aksiyondan beşi tamamlanmış, üç aylık veritabanı devretme (failover) tatbikatı devam "
            "etmektedir. Dr. Levent Sarıgül, devretme tatbikatı sonuçlarının her çeyrek Denetim "
            "Komitesi'ne raporlanmasını talep etti. ISO/IEC 27001 gözetim denetiminde tespit edilen 3 "
            "minör uygunsuzluğun tamamının 9 Eylül 2026 son tarihinden önce kapatıldığı bilgisi "
            "verildi."
        ),
        H1("4. Kararlar"),
        T(
            ("Karar No", "Konu", "Karar", "Oylama"),
            (
                ("2026/05-1", "Önceki tutanak", "2026/04 tutanağı onaylandı", "Oybirliği"),
                (
                    "2026/05-2",
                    "2027 bütçe çerçevesi",
                    "%45 gelir büyümesi, en az %16 FAVÖK marjı",
                    "Oybirliği",
                ),
                (
                    "2026/05-3",
                    "Dubai pazar araştırması",
                    "3,5 milyon TL bütçe onaylandı",
                    "Oybirliği",
                ),
                (
                    "2026/05-4",
                    "Pay opsiyon havuzu",
                    "Havuz %8'den %10'a çıkarıldı",
                    "Oyçokluğu (Kaan Ertürk çekimser)",
                ),
                (
                    "2026/05-5",
                    "Bağımsız denetçi",
                    "Atlas Kuzey Bağımsız Denetim A.Ş. seçildi",
                    "Oybirliği",
                ),
                (
                    "2026/05-6",
                    "Devretme tatbikatı",
                    "Sonuçlar her çeyrek Denetim Komitesi'ne raporlanacak",
                    "Oybirliği",
                ),
            ),
            caption="Kararlar Türk Ticaret Kanunu ve esas sözleşme hükümlerine uygun olarak alınmıştır.",
        ),
        H1("5. Dilekler ve bir sonraki toplantı"),
        P(
            "Hande Okyay, yatırımcı bültenlerinde NPS ve hizmet sürekliliği göstergelerinin çeyreklik "
            "trend olarak verilmesini istedi. Bir sonraki olağan toplantının 10 Aralık 2026 Perşembe "
            "günü saat 14:00'te Genel Merkez'de yapılmasına karar verildi. Toplantı 17:20'de sona "
            "erdi."
        ),
        P(
            "Bu tutanak raportör Zeynep Şahin tarafından hazırlanmış ve toplantıya katılan üyelerce "
            "imzalanmıştır."
        ),
    ),
)

STRATEGY = Doc(
    path="ceo-ofisi/Stratejik_Plan_2026_2028.pptx",
    title="Stratejik Plan 2026–2028",
    lang="tr",
    date=D(2026, 1, 28),
    slides=(
        Slide(
            "Stratejik Plan 2026–2028",
            subtitle="Yönetim Kurulu sunumu · 28 Ocak 2026 · Mehmet Yılmaz, CEO",
        ),
        Slide(
            "2025: başlangıç noktamız",
            bullets=(
                "2025 geliri 486,3 milyon TL (2024: 298,7 milyon TL, +%62,8)",
                "Yıl sonu ARR 16,9 milyon USD; ödeme yapan müşteri sayısı 1.180",
                "Çalışan sayısı 214; İzmir Müşteri Destek Merkezi 1 Eylül 2025'te açıldı",
                "Brüt kâr marjı %71,8, FAVÖK marjı %9,4",
                "NPS 41, brüt müşteri kaybı (logo churn) %7,8",
            ),
            notes="2025, Seri B turunun (14 Mayıs 2025, 28 milyon USD, lider yatırımcı Bosphorus "
            "Growth Partners) ardından ölçeklenme yılıydı. Rakamlar denetlenmemiş yönetim "
            "verileridir.",
        ),
        Slide(
            "Vizyon ve üç stratejik eksen",
            bullets=(
                (
                    "Vizyon: Türkiye'nin ve DACH bölgesinin en güvenilir yapay zekâ destekli "
                    "CRM platformu olmak"
                ),
                "Eksen 1 — Ürün derinliği: Nebula Assist ve sektör paketleri",
                "Eksen 2 — Uluslararası büyüme: önce DACH, ardından Körfez",
                "Eksen 3 — Verimli büyüme: her yıl FAVÖK marjında en az 3 puan iyileşme",
            ),
            notes="Eksenlerin her birinin sahibi Yönetim Kurulu'na çeyreklik rapor verir: Ürün "
            "için Merve Doğan, uluslararası büyüme için Deniz Koç, verimlilik için Ali Vural.",
        ),
        Slide(
            "2028 hedefleri",
            table=T(
                ("Gösterge", "2025 gerçekleşen", "2026 hedef", "2028 hedef"),
                (
                    ("ARR (USD)", "16,9 milyon", "25 milyon", "50 milyon"),
                    ("Uluslararası gelir payı", "%2", "%6", "%25"),
                    ("Çalışan sayısı", "214", "260", "400"),
                    ("FAVÖK marjı", "%9,4", "%14,3", "%20"),
                    ("Ödeme yapan müşteri", "1.180", "1.550", "2.600"),
                    ("NPS", "41", "45", "50"),
                ),
            ),
            notes="2028 sonu için 50 milyon USD ARR hedefi, yıllık ortalama %44 ARR büyümesi "
            "varsayar. Uluslararası gelir payı hedefi DACH ve Körfez gelirlerinin toplamıdır.",
        ),
        Slide(
            "Pazar genişlemesi",
            bullets=(
                "DACH: Berlin satış ofisi (Nebula Technology GmbH) Şubat 2026'da açılıyor",
                "AB veri yerleşimi: Frankfurt FRA-1 bölgesi 2026 üçüncü çeyrekte devrede",
                "Körfez: Dubai ofisi 2027 ikinci yarı için planlanıyor",
                "Dubai öncesi koşullar: Arapça arayüz (2027 ilk yarı) ve yerel iş ortağı",
                "2026 hedefi: Almanya'da 40 ödeme yapan müşteri",
            ),
            notes="Körfez'de halihazırda NebulaCRM kullanan 6 müşteri var; hepsi Türkiye merkezli "
            "şirketlerin bölge ofisleri. Dubai kararı 2026 içinde yapılacak bir ön "
            "fizibilite çalışmasına bağlıdır.",
        ),
        Slide(
            "Ürün yol haritası",
            table=T(
                ("Sürüm", "Plan", "Öne çıkan"),
                (
                    ("v3.2", "Şubat 2026", "Okuma replikası yönlendirmesi"),
                    ("v3.3", "Mayıs 2026", "Çok para birimli teklifler"),
                    ("v3.4", "Eylül 2026", "Nebula Assist genel kullanım"),
                    ("v3.5", "Aralık 2026", "Sektör paketleri: lojistik"),
                    ("v4.0", "2027 2. çeyrek", "Çok bölgeli aktif-aktif mimari"),
                ),
            ),
            notes="API v2'nin kullanımdan kaldırılması 31 Mart 2027'de tamamlanacak; v4.0 yalnızca "
            "API v3'ü destekleyecek.",
        ),
        Slide(
            "Organizasyon ve yetenek",
            bullets=(
                "Çalışan sayısı 2026 sonunda 260, 2028 sonunda 400",
                "Ankara Ar-Ge ofisi 2027 sonuna kadar 60 kişiye büyüyecek",
                "İzmir destek merkezi 2027'de 7/24 vardiyaya geçecek",
                "Berlin ekibi 2026 sonunda en fazla 12 kişi",
                "Gönüllü personel devir hızı hedefi: %12'nin altında",
            ),
            notes="Berlin kadro tavanı Yönetim Kurulu tarafından ayrıca onaylanacaktır.",
        ),
        Slide(
            "Finansman ve sermaye tahsisi",
            bullets=(
                "Seri B fonu ile 2028'e kadar yeni bir finansman turu planlanmıyor",
                "Küçük ölçekli şirket satın almaları için işlem başına en fazla 5 milyon USD",
                "Yatırım harcamasının (CAPEX) gelire oranı %5'in altında tutulacak",
                "Çalışan pay opsiyon havuzu: tam seyreltilmiş sermayenin %8'i",
            ),
            notes="Satın alma adayları: sektörel entegrasyon ve konuşma analitiği alanlarında "
            "faaliyet gösteren yerli girişimler.",
        ),
        Slide(
            "Başlıca riskler",
            table=T(
                ("Risk", "Etki", "Önlem"),
                (
                    ("Kur oynaklığı", "Yüksek", "USD/EUR gelir payını artırmak"),
                    ("Yetenek rekabeti", "Yüksek", "Ankara ve İzmir'de işe alım"),
                    ("Hizmet kesintisi", "Orta", "FRA-1 ve DR tatbikatları"),
                    ("Regülasyon (KVKK, GDPR)", "Orta", "AB veri yerleşimi"),
                    ("Yapay zekâ kalitesi", "Orta", "Kaynak gösteren yanıtlar"),
                ),
            ),
        ),
        Slide(
            "İzleme ve sonraki adımlar",
            bullets=(
                "Stratejik göstergeler her çeyrek Yönetim Kurulu'na raporlanır",
                "Yıllık strateji gözden geçirmesi her yıl Ocak ayında yapılır",
                "2026 hedeflerinin ara değerlendirmesi: Temmuz 2026",
                "Sorumlu: Zeynep Şahin, CEO Ofisi Müdürü",
            ),
            notes="Plan, Yönetim Kurulu'nun 28 Ocak 2026 tarihli toplantısında görüşülmüş ve "
            "oybirliğiyle kabul edilmiştir.",
        ),
    ),
)

MEMO = Doc(
    path="ceo-ofisi/Genelge_Maslak_10_Kat_Tadilati.png",
    title="GENELGE: Maslak 10. Kat Tadilatı",
    lang="tr",
    date=D(2026, 11, 2),
    meta=(
        ("Sayı", "CEO-2026-031"),
        ("Kimden", "Mehmet Yılmaz, CEO"),
        ("Kime", "İstanbul Genel Merkez çalışanları"),
    ),
    classification="Şirket İçi",
    blocks=(
        P(
            "Maslak Genel Merkez binamızın 10. katında 14-18 Aralık 2026 tarihleri arasında tadilat "
            "yapılacaktır."
        ),
        P(
            "Bu tarihlerde 10. katta oturan Ar-Ge İstanbul ve Ürün Yönetimi ekipleri uzaktan "
            "çalışacaktır. 9. ve 11. katlar normal şekilde açık kalacaktır."
        ),
        P(
            "Tadilatla birlikte yeni kartlı geçiş sistemine geçiyoruz. Yeni personel kartlarınızı en "
            "geç 27 Kasım 2026 tarihine kadar resepsiyondan teslim almanız gerekmektedir. Eski "
            "kartlar 1 Aralık 2026 itibarıyla çalışmayacaktır."
        ),
        P(
            "10. kattaki toplantı odalarının rezervasyonları bu süre boyunca 11. kattaki Boğaz ve "
            "Galata salonlarına aktarılmıştır."
        ),
        P("Sorularınız için: Kerem Acar, İcra Asistanı, dahili 1042."),
    ),
)

DOCS = [INVESTOR_UPDATE, BOARD_MINUTES, STRATEGY, MEMO]
