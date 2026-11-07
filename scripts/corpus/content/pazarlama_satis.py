# SPDX-License-Identifier: Apache-2.0

"""Pazarlama ve Satış: price lists (2026 + archived 2025), Q3 sales deck, partner guide."""

from model import H1, H2, OL, UL, D, Doc, P, Sheet, Slide, T

FIYAT_2026 = Doc(
    path="pazarlama-satis/Fiyat_Listesi_2026.xlsx",
    title="NebulaCRM Fiyat Listesi 2026",
    lang="tr",
    date=D(2025, 12, 15),
    doc_no="PS-FYT-2026",
    sheets=(
        Sheet(
            "TL Fiyat Listesi",
            (
                "Plan",
                "Aylık Fiyat (TL/kullanıcı)",
                "Asgari Kullanıcı",
                "Azami Kullanıcı",
                "Depolama (GB/kullanıcı)",
                "API Limiti (istek/dk)",
                "Erişilebilirlik Taahhüdü",
            ),
            (
                ("Başlangıç", 690, 3, 25, 5, 60, "Taahhüt yok (hedef %99,5)"),
                ("Profesyonel", 1290, 5, "Sınırsız", 20, 300, "%99,5"),
                ("Kurumsal", 2150, 25, "Sınırsız", 50, 1200, "%99,9"),
                (
                    "Kurumsal Plus",
                    "3.400 TL'den başlayan (teklif üzerine)",
                    100,
                    "Sınırsız",
                    100,
                    3000,
                    "%99,95",
                ),
            ),
            title="NebulaCRM 2026 Liste Fiyatları (TL, KDV hariç)",
            notes=(
                "Fiyatlar KDV hariçtir ve 1 Ocak 2026 tarihinden itibaren tüm yeni teklifler ve yenilemeler için geçerlidir.",
                "Bu liste, 31 Aralık 2025 itibarıyla geçersiz olan 2025 fiyat listesinin (PS-FYT-2025) yerini alır.",
                "Destek ilk yanıt süreleri ve hizmet kredileri için Müşteri Deneyimi'nin Destek SLA Matrisi 2026 dokümanına bakınız.",
                "Hazırlayan: Cansu Aydın (Pazarlama Uzmanı) · Onaylayan: Deniz Koç (Pazarlama ve Satış Müdürü) · 15.12.2025",
            ),
        ),
        Sheet(
            "EUR Fiyat Listesi (DACH)",
            (
                "Plan",
                "Aylık Fiyat (EUR/kullanıcı)",
                "Asgari Kullanıcı",
                "Sözleşme Tarafı",
                "Barındırma",
            ),
            (
                ("Starter", 24, 3, "Nebula Technology GmbH", "IST-1 (varsayılan)"),
                ("Professional", 45, 5, "Nebula Technology GmbH", "IST-1 veya FRA-1"),
                ("Enterprise", 75, 25, "Nebula Technology GmbH", "IST-1 veya FRA-1"),
                (
                    "Enterprise Plus",
                    "119 EUR'dan başlayan (teklif üzerine)",
                    100,
                    "Nebula Technology GmbH",
                    "FRA-1 önerilir",
                ),
            ),
            title="DACH Bölgesi Liste Fiyatları (EUR, MwSt. hariç)",
            notes=(
                "Almanya, Avusturya ve İsviçre müşterilerine 2 Şubat 2026'dan itibaren Berlin'deki Nebula Technology GmbH üzerinden EUR olarak faturalandırılır.",
                "FRA-1 (Frankfurt) AB bölgesi devreye alındığında Professional ve üzeri planlarda ek ücret olmadan seçilebilir.",
                "EUR fiyatları kur dalgalanmasından bağımsızdır; yılda bir kez, Ocak ayında gözden geçirilir.",
            ),
        ),
        Sheet(
            "Ek Modüller",
            ("Modül / Hizmet", "Birim", "2026 Fiyatı (TL)", "2025 Fiyatı (TL)", "Uygun Planlar"),
            (
                (
                    "NebulaAnalytics",
                    "kullanıcı/ay",
                    390,
                    290,
                    "Profesyonel, Kurumsal, Kurumsal Plus",
                ),
                (
                    "Nebula Assist",
                    "kullanıcı/ay",
                    240,
                    "Yeni modül",
                    "Profesyonel (Kurumsal ve Kurumsal Plus'a dahil)",
                ),
                ("Ek depolama paketi (100 GB)", "paket/ay", 450, 350, "Tüm planlar"),
                ("Sandbox ortamı", "ortam/ay", 6500, 5000, "Profesyonel, Kurumsal"),
                ("SSO (SAML) eklentisi", "kullanıcı/ay", 120, 90, "Profesyonel (Kurumsal'a dahil)"),
                ("Premium eğitim (1 gün, uzaktan)", "gün", 28000, 22000, "Tüm planlar"),
                (
                    "Veri taşıma hizmeti",
                    "proje (başlangıç)",
                    85000,
                    65000,
                    "Kurumsal, Kurumsal Plus",
                ),
                ("Ek TAM saati", "saat", 4200, 3300, "Kurumsal Plus"),
            ),
            title="Ek Modüller ve Profesyonel Hizmetler",
            notes=(
                "Nebula Assist, genel kullanıma açıldığı sürümle birlikte faturalanmaya başlar; beta süresince ücretsizdir.",
                "Profesyonel hizmetler (eğitim, veri taşıma, TAM saati) ön ödeme indirimine dahil edilmez.",
            ),
        ),
        Sheet(
            "Ön Ödeme İndirimleri",
            ("Ödeme / Hacim Modeli", "İndirim", "Fatura Dönemi", "Not"),
            (
                ("Aylık ödeme", "%0", "Aylık", "Asgari taahhüt yok"),
                ("Yıllık peşin ödeme", "%15", "Yıllık", "2025 listesinde %12 idi"),
                ("2 yıllık peşin ödeme", "%22", "Peşin (24 ay)", "2025 listesinde %18 idi"),
                ("Hacim: 250–499 kullanıcı", "%5", "Sözleşmeye göre", "Kurumsal ve Kurumsal Plus"),
                ("Hacim: 500–999 kullanıcı", "%8", "Sözleşmeye göre", "Kurumsal ve Kurumsal Plus"),
                ("Hacim: 1.000+ kullanıcı", "%12", "Sözleşmeye göre", "Kurumsal ve Kurumsal Plus"),
                ("Dernek ve vakıflar", "%30", "Yıllık", "Başlangıç ve Profesyonel; belge gerekir"),
                (
                    "Girişim programı (ilk yıl)",
                    "%40",
                    "Yıllık",
                    "Kuruluşu 3 yıldan yeni, en fazla 25 kullanıcı",
                ),
            ),
            title="Ön Ödeme ve Hacim İndirimleri",
            notes=(
                "Ön ödeme ve hacim indirimleri birlikte uygulanabilir; birleşik oran İndirim Yetkileri sayfasındaki toplam indirim oranına dahildir.",
            ),
        ),
        Sheet(
            "İndirim Yetkileri",
            ("Toplam İndirim Oranı", "Onay Yetkilisi", "Unvan", "Onay Kanalı", "Azami Onay Süresi"),
            (
                (
                    "%10'a kadar",
                    "Satış temsilcisi",
                    "Satış Temsilcisi",
                    "CRM teklif ekranı",
                    "Anında",
                ),
                (
                    "%10'un üzeri – %25'e kadar",
                    "Deniz Koç",
                    "Pazarlama ve Satış Müdürü",
                    "Teklif onay akışı",
                    "1 iş günü",
                ),
                (
                    "%25'in üzeri",
                    "Mehmet Yılmaz",
                    "CEO",
                    "Teklif onay akışı + yazılı gerekçe",
                    "2 iş günü",
                ),
            ),
            title="Doğrudan Satış İndirim Yetki Matrisi (2026)",
            notes=(
                "Toplam indirim oranı; liste fiyatı üzerinden uygulanan ön ödeme, hacim ve özel indirimlerin toplamıdır.",
                "Partner marjları bu matrisin dışındadır; partner kanalına ek müşteri indirimi verilirse aynı matris uygulanır.",
                "Onaysız teklif müşteriye gönderilemez; CRM teklif ekranı yetki aşımında teklifi otomatik olarak kilitler.",
            ),
        ),
    ),
)


FIYAT_2025 = Doc(
    path="pazarlama-satis/Fiyat_Listesi_2025_ARSIV.pdf",
    title="NebulaCRM Fiyat Listesi 2025",
    subtitle="ARŞİV — 31 Aralık 2025 itibarıyla geçersiz",
    lang="tr",
    date=D(2024, 12, 16),
    doc_no="PS-FYT-2025",
    classification="Şirket İçi — Arşiv",
    meta=(
        ("Sürüm", "2025.1"),
        ("Hazırlayan", "Cansu Aydın, Pazarlama Uzmanı"),
        ("Onaylayan", "Deniz Koç, Pazarlama ve Satış Müdürü"),
        ("Geçerlilik", "1 Ocak 2025 – 31 Aralık 2025"),
        ("Yerine geçen", "NebulaCRM Fiyat Listesi 2026 (PS-FYT-2026)"),
    ),
    blocks=(
        H1("Arşiv Uyarısı"),
        P(
            "Bu doküman yalnızca kayıt amacıyla saklanmaktadır. 1 Ocak 2026 tarihinden itibaren "
            "yeni teklif, yenileme ve sözleşme değişikliklerinde NebulaCRM Fiyat Listesi 2026 "
            "(Fiyat_Listesi_2026.xlsx) kullanılır. 2025 içinde imzalanmış yıllık sözleşmeler, "
            "sözleşme bitiş tarihine kadar bu listedeki fiyatlarla faturalanmaya devam eder; "
            "yenileme anında 2026 fiyatlarına geçilir."
        ),
        H1("1. Genel Koşullar"),
        P(
            "Tüm fiyatlar Türk lirası cinsindendir, KDV hariçtir ve kullanıcı başına aylık olarak "
            "ifade edilir. Kullanıcı, sisteme ad soyad ile tanımlanmış ve oturum açabilen kişidir; "
            "salt okunur portal kullanıcıları lisans sayısına dahil edilmez. Plan yükseltmeleri ay "
            "içinde gün bazında oranlanır, plan düşürmeleri bir sonraki fatura döneminde geçerli olur."
        ),
        P(
            "2025 yılında EUR fiyat listesi yayımlanmamıştır. Yurt dışı müşterilere verilen teklifler "
            "TL liste fiyatı esas alınarak hazırlanmış ve Finans Müdürlüğü'nün onayladığı kurla "
            "faturalandırılmıştır."
        ),
        H1("2. Plan Fiyatları"),
        T(
            ("Plan", "Aylık fiyat", "Asgari kullanıcı", "Azami kullanıcı"),
            (
                ("Başlangıç", "520 TL", "3", "25"),
                ("Profesyonel", "990 TL", "5", "Sınırsız"),
                ("Kurumsal", "1.650 TL", "25", "Sınırsız"),
                ("Kurumsal Plus", "2.600 TL'den başlayan", "100", "Sınırsız"),
            ),
            caption="Tablo 1. 2025 liste fiyatları (kullanıcı başına aylık, KDV hariç).",
            widths=(1.4, 1.6, 1.0, 1.0),
        ),
        P(
            "Kurumsal Plus fiyatı; atanmış teknik hesap yöneticisi (TAM), özel veritabanı seçeneği ve "
            "genişletilmiş saklama gereksinimlerine göre teklif üzerine belirlenir. 2025 yılında "
            "verilen en düşük Kurumsal Plus fiyatı kullanıcı başına aylık 2.600 TL'dir."
        ),
        H2("2.1 Plan Bazında Teknik Sınırlar"),
        T(
            ("Plan", "Depolama", "API limiti"),
            (
                ("Başlangıç", "5 GB/kullanıcı", "60 istek/dk"),
                ("Profesyonel", "15 GB/kullanıcı", "200 istek/dk"),
                ("Kurumsal", "50 GB/kullanıcı", "1.200 istek/dk"),
                ("Kurumsal Plus", "100 GB/kullanıcı", "3.000 istek/dk"),
            ),
            caption="Tablo 2. 2025 plan sınırları. API limitleri erişim anahtarı başınadır.",
            widths=(1.4, 1.4, 1.4),
        ),
        P(
            "Profesyonel planda API hız limiti 2025 boyunca dakikada 200 istek olarak uygulanmıştır. "
            "Bu sınır, liste dışı bir taahhüt olarak hiçbir teklifte artırılmamalıdır; daha yüksek "
            "entegrasyon hacmine ihtiyaç duyan müşterilere Kurumsal plan önerilir."
        ),
        H1("3. Ek Modüller ve Hizmetler"),
        T(
            ("Modül / hizmet", "Birim", "Fiyat"),
            (
                ("NebulaAnalytics", "kullanıcı/ay", "290 TL"),
                ("Ek depolama (100 GB)", "paket/ay", "350 TL"),
                ("Sandbox ortamı", "ortam/ay", "5.000 TL"),
                ("SSO (SAML) eklentisi", "kullanıcı/ay", "90 TL"),
                ("Premium eğitim (1 gün)", "gün", "22.000 TL"),
                ("Veri taşıma hizmeti", "proje (başlangıç)", "65.000 TL"),
            ),
            caption="Tablo 3. 2025 ek modül ve profesyonel hizmet fiyatları.",
            widths=(1.8, 1.3, 1.1),
        ),
        H1("4. Ödeme Modelleri ve İndirimler"),
        UL(
            "Aylık ödeme: indirim uygulanmaz, asgari taahhüt yoktur.",
            "Yıllık peşin ödemede %12 indirim uygulanır.",
            "2 yıllık peşin ödemede %18 indirim uygulanır.",
            "500 ve üzeri kullanıcılı Kurumsal sözleşmelerde %6 hacim indirimi eklenebilir.",
            "Dernek ve vakıflara Başlangıç ve Profesyonel planlarda %25 indirim uygulanır.",
        ),
        H2("4.1 İndirim Onay Yetkileri (2025)"),
        P(
            "Liste fiyatına göre toplam indirim %10'a kadar ise satış temsilcisi tarafından, %20'ye "
            "kadar ise Pazarlama ve Satış Müdürü Deniz Koç tarafından onaylanır. %20'nin üzerindeki "
            "tüm indirimler CEO Mehmet Yılmaz'ın yazılı onayını gerektirir. Ön ödeme ve hacim "
            "indirimleri toplam orana dahildir."
        ),
        H1("5. Teklif ve Faturalama Kuralları"),
        OL(
            "Teklifler 30 gün geçerlidir; süre dolduğunda yeniden onay alınır.",
            "Yıllık sözleşmeler sözleşme süresi boyunca fiyat korumalıdır.",
            "Faturalar her ayın ilk iş günü kesilir; ödeme vadesi fatura tarihinden itibaren 15 gündür.",
            "Vadesinde ödenmeyen hesaplarda 30. günde yazılı hatırlatma, 45. günde hizmet kısıtlaması uygulanır.",
        ),
        P(
            "Bu listeye ilişkin sorular için Pazarlama ve Satış Müdürlüğü'ne "
            "satis@nebulacrm.example adresinden ulaşılabilir. Arşivlenmiş fiyatlar müşteri "
            "iletişiminde referans olarak kullanılmamalıdır."
        ),
    ),
)


SATIS_Q3 = Doc(
    path="pazarlama-satis/Satis_Performansi_2026_Q3.pptx",
    title="Satış Performansı — 2026 3. Çeyrek",
    lang="tr",
    date=D(2026, 10, 6),
    slides=(
        Slide(
            "Satış Performansı — 2026 3. Çeyrek",
            subtitle="Pazarlama ve Satış Müdürlüğü · Deniz Koç · Yönetim toplantısı, 6 Ekim 2026",
        ),
        Slide(
            "Çeyreğin Özeti",
            bullets=(
                "Yeni ARR 2,1 milyon USD; çeyrek kotasının %103'ü gerçekleşti",
                "112 yeni müşteri kazanıldı; 30 Eylül 2026 itibarıyla toplam müşteri sayısı 1.412",
                "Kazanma oranı %24'ten %27'ye yükseldi, satış döngüsü 64 güne indi",
                "Lodos Lojistik genişlemesi çeyreğin en büyük tek anlaşması oldu",
                "Nebula Assist 15 Eylül'de genel kullanıma açıldı; Profesyonel planda ilk 2 haftada 31 müşteriye ek satış",
            ),
            notes="Kota 2,04 milyon USD idi. Çeyreği kotanın üzerinde kapatan 9 temsilciden "
            "ikisi Berlin ekibinden. Eylül ayı tek başına yeni ARR'ın %46'sını getirdi.",
        ),
        Slide(
            "Temel Göstergeler",
            table=T(
                ("Gösterge", "2026 Ç2", "2026 Ç3", "Değişim"),
                (
                    ("Yeni ARR", "$1.8M", "$2.1M", "+%17"),
                    ("Yeni müşteri (logo)", "98", "112", "+14"),
                    ("Kazanma oranı", "%24", "%27", "+3 puan"),
                    ("Ortalama satış döngüsü", "71 gün", "64 gün", "−7 gün"),
                    ("Dönem sonu pipeline", "$8.6M", "$9.8M", "+%14"),
                    ("Kota gerçekleşmesi", "%96", "%103", "+7 puan"),
                ),
            ),
            notes="Kazanma oranı, nitelikli fırsat aşamasına geçmiş ve çeyrek içinde "
            "sonuçlanmış fırsatlar üzerinden hesaplanır. Pipeline rakamı ağırlıksızdır.",
        ),
        Slide(
            "Segment ve Bölge Kırılımı",
            bullets=(
                "Türkiye'de yeni ARR'ın %59'u Kurumsal ve Kurumsal Plus segmentinden geldi",
                "DACH bölgesi 30 Eylül itibarıyla 37 müşteriye ulaştı",
            ),
            table=T(
                ("Segment / Bölge", "Yeni ARR", "Yeni müşteri"),
                (
                    ("Türkiye — Kurumsal ve Kurumsal Plus", "$1.24M", "21"),
                    ("Türkiye — Profesyonel", "$0.62M", "54"),
                    ("Türkiye — Başlangıç", "$0.11M", "28"),
                    ("DACH (Berlin)", "$0.13M", "9"),
                ),
            ),
            notes="Berlin ekibi 10 kişi; DACH'ta ortalama sözleşme değeri Türkiye Profesyonel "
            "segmentinin yaklaşık 1,3 katı.",
        ),
        Slide(
            "Öne Çıkan Anlaşmalar",
            table=T(
                ("Müşteri", "Kapsam", "Plan", "Toplam indirim"),
                (
                    ("Lodos Lojistik A.Ş.", "+1.100 kullanıcı (genişleme)", "Kurumsal Plus", "%28"),
                    ("Poyraz Sigorta", "420 kullanıcı (yeni)", "Kurumsal", "%18"),
                    ("Mavikent Hastaneleri", "260 kullanıcı (yeni)", "Kurumsal", "%12"),
                    ("Karayel Enerji", "140 kullanıcı (genişleme)", "Kurumsal", "%9"),
                    ("Spreewerk Logistik GmbH", "85 kullanıcı (yeni)", "Enterprise", "%10"),
                ),
            ),
            notes="Lodos Lojistik genişlemesiyle müşterinin toplam kullanıcı sayısı 3.500'e "
            "ulaştı. Sözleşme 3 yıllık; %28 toplam indirim, hacim ve yıllık peşin ödeme "
            "indirimlerini de içeriyor. Anlaşmayı Mert Özdemir yönetti.",
        ),
        Slide(
            "Kanal ve Partner Katkısı",
            bullets=(
                "Partner kaynaklı yeni ARR 0,40 milyon USD (toplamın %19'u)",
                "Kuzgun Danışmanlık (Gold) çeyrekte 6 anlaşma ile en yüksek katkıyı verdi",
                "Pusula Bilişim 1 Eylül 2026'da Silver'dan Gold seviyesine yükseldi",
                "Çeyrekte 47 fırsat kaydı (deal registration) onaylandı; ortalama onay süresi 1,4 iş günü",
            ),
            notes="Partner kanalında ortalama satış döngüsü 52 gün; doğrudan satıştan 12 gün daha kısa.",
        ),
        Slide(
            "Kaybedilen Fırsatlar",
            bullets=(
                "Fiyat: kayıpların %34'ü",
                "Eksik entegrasyon (özellikle sektörel ERP bağlantıları): %21",
                "Müşteri kararı erteledi: %19",
                "Rakip ürün tercihi: %16",
                "Diğer (bütçe kesintisi, birleşme): %10",
            ),
            notes="Fiyat kaynaklı kayıpların üçte ikisi Başlangıç ve Profesyonel segmentinde. "
            "Ürün Yönetimi ile entegrasyon talepleri listesi 20 Ekim'de paylaşılacak.",
        ),
        Slide(
            "Pazarlama Katkısı",
            table=T(
                ("Gösterge", "2026 Ç3"),
                (
                    ("Pazarlama nitelikli lead (MQL)", "2.940"),
                    ("Satış nitelikli lead (SQL)", "610"),
                    ("SQL başına maliyet", "7.800 TL"),
                    ("Nebula Assist lansman webinarı katılımcısı", "1.150"),
                ),
            ),
            notes="Lansman webinarı 17 Eylül'de yapıldı; Cansu Aydın koordine etti. "
            "Webinar sonrası 83 demo talebi alındı.",
        ),
        Slide(
            "4. Çeyrek Öncelikleri",
            bullets=(
                "Ç4 yeni ARR hedefi 2,4 milyon USD",
                "Profesyonel müşterilerde Nebula Assist ek satışı: 120 müşteri hedefi",
                "DACH'ta 15 yeni müşteri; FRA-1 barındırma seçeneği ile kamu dışı regüle sektörler",
                "2027 fiyat listesi çalışması 1 Kasım 2026'da başlıyor; taslak 1 Aralık'ta",
                "Yıl sonu yoğunluğu için teklif onay akışında 2 iş günü kuralına sıkı uyum",
            ),
            notes="Yıl sonunda %25 üzeri indirim talepleri artıyor; gerekçe notu olmadan "
            "gönderilen talepler onay akışına alınmayacak.",
        ),
    ),
)


PARTNER = Doc(
    path="pazarlama-satis/Partner_Program_Guide_2026.md",
    title="Nebula Partner Program Guide 2026",
    lang="en",
    date=D(2026, 2, 10),
    doc_no="PS-PRT-2026",
    meta=(
        ("Version", "2026.1"),
        ("Program owner", "Deniz Koç, Pazarlama ve Satış Müdürü"),
        ("Partner operations", "Cansu Aydın"),
        ("Effective", "1 March 2026"),
    ),
    blocks=(
        H1("1. Purpose"),
        P(
            "The Nebula Partner Program helps consultancies, system integrators and regional "
            "resellers sell, implement and support NebulaCRM. This guide sets out the partner tiers, "
            "the requirements to reach and keep each tier, the commercial terms, and the rules for "
            "deal registration. It replaces the 2025 partner handbook. Questions go to "
            "partners@nebulacrm.example; all registrations and certifications are handled in the "
            "partner portal at partner.nebulacrm.example."
        ),
        H1("2. Partner tiers"),
        P(
            "There are four tiers: Registered, Silver, Gold and Platinum. Every new partner starts "
            "at Registered after signing the partner agreement and completing onboarding. Tiers are "
            "reviewed once a year in January based on the previous calendar year's results; a "
            "partner that exceeds the next tier's thresholds mid-year may request an early upgrade, "
            "which takes effect on the first day of the following month."
        ),
        T(
            (
                "Tier",
                "Certified consultants",
                "Annual partner-sourced bookings",
                "Customer CSAT",
                "Resale margin",
            ),
            (
                ("Registered", "1", "none", "none", "10%"),
                ("Silver", "3", "TRY 1,500,000", "≥ 85%", "15%"),
                ("Gold", "10", "TRY 4,000,000", "≥ 88%", "20%"),
                ("Platinum", "20", "TRY 10,000,000", "≥ 90%", "25%"),
            ),
            caption="Table 1. Tier requirements and resale margins. Margins apply to the list price "
            "of NebulaCRM subscriptions and add-on modules.",
        ),
        P(
            "Bookings count the first-year contract value of new customers and expansions that the "
            "partner sourced and registered. Renewals count at 50% of their value. CSAT is measured "
            "through the post-implementation survey sent to the customer's project owner."
        ),
        H2("2.1 Tier benefits"),
        T(
            ("Benefit", "Registered", "Silver", "Gold", "Platinum"),
            (
                ("Not-for-resale (NFR) licenses", "2", "5", "15", "30"),
                ("Market development funds", "none", "none", "2% of bookings", "3% of bookings"),
                ("Dedicated partner manager", "no", "no", "yes", "yes"),
                ("Listing in partner directory", "no", "yes", "yes", "featured"),
                ("Early access to releases", "no", "no", "yes", "yes"),
            ),
            caption="Table 2. Benefits by tier.",
        ),
        P(
            "Market development funds (MDF) are accrued quarterly and must be used within the "
            "following two quarters for jointly approved activities such as events, webinars and "
            "localized content. Unused MDF does not roll over."
        ),
        H1("3. Deal registration"),
        OL(
            "The partner registers the opportunity in the partner portal before the first "
            "customer demo, with the customer's legal name, expected user count and plan.",
            "Nebula approves or rejects the registration within 2 business days.",
            "An approved registration protects the opportunity for 90 days. It can be extended "
            "once by 30 days if the partner shows documented progress.",
            "If two partners register the same opportunity, the first complete registration wins.",
            "Registered deals that close within the protection period earn an extra 5 percentage "
            "points of margin on the first-year contract value.",
        ),
        P(
            "Direct sales will not pursue an opportunity that a partner has registered and that is "
            "under protection. Opportunities that the customer brings directly to Nebula before any "
            "registration remain with direct sales."
        ),
        H1("4. Commercial terms"),
        UL(
            "Resale: the partner buys at list price minus its tier margin and invoices the customer.",
            "Referral only: partners that do not resell receive a referral fee of 10% of the "
            "first-year contract value, paid after the customer's first payment.",
            "Additional customer discounts on top of the partner margin follow Nebula's direct "
            "sales discount authority matrix in the current price list.",
            "Nebula invoices partners monthly; payment is due within 30 days of the invoice date.",
            "Partners in Germany, Austria and Switzerland contract with Nebula Technology GmbH "
            "and buy from the EUR price list.",
        ),
        H1("5. Certification"),
        P(
            "Partner consultants become Nebula Certified Consultants by passing the online "
            "certification exam. The passing score is 75% and the certificate is valid for 24 "
            "months. The exam fee is TRY 4,500 per attempt and is waived for Gold and Platinum "
            "partners. A consultant counts toward only one partner's tier at a time."
        ),
        P(
            "Implementation projects for Kurumsal and Kurumsal Plus customers must be led by a "
            "certified consultant. Nebula's Customer Success team may review any project and can "
            "require a remediation plan if the customer's CSAT falls below the tier threshold."
        ),
        H1("6. Conduct and termination"),
        P(
            "Partners must follow Nebula's ethics rules, including the gift and hospitality limits, "
            "when dealing with customers and Nebula employees. Either party may terminate the partner "
            "agreement with 60 days' written notice. On termination, customers keep their "
            "subscriptions and are transferred to direct sales or to another partner of their choice."
        ),
        H1("7. Contacts"),
        UL(
            "Program owner: Deniz Koç",
            "Partner operations and portal: Cansu Aydın",
            "Commercial questions and deal desk: satis@nebulacrm.example",
            "General enquiries: partners@nebulacrm.example",
        ),
    ),
)

DOCS = [FIYAT_2026, FIYAT_2025, SATIS_Q3, PARTNER]
