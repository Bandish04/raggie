# SPDX-License-Identifier: Apache-2.0

"""Finans: 2026 budget workbook, purchasing procedure, travel policy, Q3 results."""

from model import H1, UL, D, Doc, P, Sheet, T

BUDGET = Doc(
    path="finans/Butce_ve_Gider_Plani_2026.xlsx",
    title="2026 Bütçe ve Gider Planı",
    lang="tr",
    date=D(2026, 1, 5),
    sheets=(
        Sheet(
            "Özet",
            ("Kalem", "Birim", "2025 Gerçekleşen", "2026 Bütçe", "Değişim (%)"),
            (
                ("Gelir", "milyon TL", 486.3, 742.0, 52.6),
                ("Brüt kâr", "milyon TL", 349.2, 541.7, 55.1),
                ("Brüt kâr marjı", "%", 71.8, 73.0, ""),
                ("Departman faaliyet giderleri (OPEX)", "milyon TL", 291.8, 416.9, 42.9),
                ("Ortak giderler (kira, sigorta, danışmanlık)", "milyon TL", 11.7, 18.6, 59.0),
                ("FAVÖK", "milyon TL", 45.7, 106.2, 132.4),
                ("FAVÖK marjı", "%", 9.4, 14.3, ""),
                ("Yatırım harcaması (CAPEX)", "milyon TL", 19.6, 34.8, 77.6),
                ("Yıl sonu çalışan sayısı", "kişi", 214, 260, 21.5),
                ("Yıl sonu ödeme yapan müşteri sayısı", "adet", 1180, 1550, 31.4),
                ("Ortalama kur varsayımı", "TL/USD", 38.6, 42.5, ""),
            ),
            title="Nebula Teknoloji A.Ş. — 2026 Bütçe Özeti (Yönetim Kurulu onaylı, sürüm 1.2)",
            notes=(
                "Tutarlar KDV hariçtir. 2025 sütunu bağımsız denetimden geçmemiş yönetim raporlarına dayanır.",
                "Gelir bütçesi 742,0 milyon TL; abonelik gelirinin payı %91 olarak varsayılmıştır.",
                "Hazırlayan: Tolga Yıldırım (Finans Analisti). Kontrol: Buse Erdoğan (Mali Müşavir).",
            ),
        ),
        Sheet(
            "Departman Bütçeleri",
            (
                "Departman",
                "Bütçe Sahibi",
                "2025 Gerçekleşen (milyon TL)",
                "2026 Bütçe (milyon TL)",
                "Değişim (%)",
                "2026 Hedef Kadro",
            ),
            (
                ("Ar-Ge", "Ayşe Demir", 121.6, 168.4, 38.5, 92),
                ("Bilgi Teknolojileri", "Emre Kaya", 30.4, 41.2, 35.5, 18),
                ("Pazarlama ve Satış", "Deniz Koç", 64.2, 96.7, 50.6, 44),
                ("Müşteri Deneyimi", "Can Öztürk", 24.8, 38.9, 56.9, 46),
                ("Ürün Yönetimi", "Merve Doğan", 15.1, 22.3, 47.7, 14),
                ("İnsan Kaynakları", "Burak Çelik", 10.2, 14.6, 43.1, 9),
                ("Finans", "Ali Vural", 7.3, 9.8, 34.2, 8),
                ("Hukuk ve Uyum", "Elif Aydın", 5.1, 7.4, 45.1, 6),
                ("Kalite Yönetimi", "Selin Arslan", 4.4, 6.1, 38.6, 11),
                ("CEO Ofisi", "Zeynep Şahin", 8.7, 11.5, 32.2, 12),
                ("TOPLAM", "", 291.8, 416.9, 42.9, 260),
            ),
            title="Departman Bazında Faaliyet Gideri Bütçesi (OPEX)",
            notes=(
                "Departman bütçelerine personel, yan haklar, seyahat, yazılım abonelikleri ve eğitim giderleri dahildir.",
                "Müşteri Deneyimi artışının ana kaynağı, 1 Eylül 2025'te açılan İzmir Müşteri Destek Merkezi'nin tam yıl etkisidir.",
                "Ortak giderler (kira, sigorta, danışmanlık) departmanlara dağıtılmamış olup Özet sayfasında ayrıca gösterilir.",
            ),
        ),
        Sheet(
            "Yan Haklar ve Ödenekler",
            ("Kalem", "Periyot", "Kapsam", "2025 (TL)", "2026 (TL)", "Dayanak"),
            (
                (
                    "Uzaktan çalışma ödeneği",
                    "Aylık, kişi başı",
                    "Uygunluk kriterini sağlayan hibrit ve uzaktan çalışanlar",
                    1900,
                    2750,
                    "IK-POL-012 madde 6",
                ),
                (
                    "Ev-ofis kurulum desteği",
                    "Tek seferlik",
                    "Hibrit veya uzaktan modele ilk kez geçen çalışanlar",
                    5000,
                    7500,
                    "IK-POL-012 madde 6",
                ),
                (
                    "Yemek kartı",
                    "Günlük (iş günü)",
                    "Türkiye ofislerindeki tüm çalışanlar",
                    250,
                    330,
                    "İK uygulama talimatı",
                ),
                (
                    "Eğitim bütçesi",
                    "Yıllık, kişi başı",
                    "Tüm çalışanlar",
                    12000,
                    18000,
                    "IK-REH-004",
                ),
                (
                    "Spor ve sağlık desteği",
                    "Aylık, kişi başı",
                    "Tüm çalışanlar",
                    600,
                    900,
                    "İK uygulama talimatı",
                ),
                (
                    "Özel sağlık sigortası primi",
                    "Yıllık, kişi başı",
                    "Çalışan ve birinci derece aile üyeleri",
                    24600,
                    38400,
                    "Grup poliçesi",
                ),
                (
                    "Doğum yardımı",
                    "Tek seferlik",
                    "Tüm çalışanlar",
                    10000,
                    15000,
                    "İK uygulama talimatı",
                ),
                (
                    "Evlilik yardımı",
                    "Tek seferlik",
                    "Tüm çalışanlar",
                    6000,
                    9000,
                    "İK uygulama talimatı",
                ),
                (
                    "Vardiya yemek desteği (gece vardiyası)",
                    "Vardiya başına",
                    "İzmir Müşteri Destek Merkezi",
                    180,
                    260,
                    "İzmir vardiya yönergesi",
                ),
            ),
            title="2026 Yan Haklar ve Ödenekler (1 Ocak 2026'dan itibaren geçerli)",
            notes=(
                "Ödenekler bordro üzerinden ödenir; tutarlar net ödeme tutarıdır.",
                "Uzaktan çalışma ödeneğine hak kazanma koşulları İnsan Kaynakları'nın Uzaktan ve Hibrit Çalışma Politikası'nda (IK-POL-012) tanımlanır.",
                "Berlin çalışanlarının yan hakları Nebula Technology GmbH bütçesinde EUR cinsinden ayrıca planlanmıştır.",
            ),
        ),
        Sheet(
            "Seyahat Varsayımları",
            ("Kalem", "Birim", "2025", "2026", "Kaynak"),
            (
                ("Yurt içi harcırah", "TL/gün", 950, 1400, "FIN-POL-007"),
                ("Yurt dışı harcırah", "EUR/gün", 80, 95, "FIN-POL-007"),
                ("Otel üst limiti — İstanbul", "TL/gece", 3100, 4500, "FIN-POL-007"),
                ("Otel üst limiti — diğer şehirler", "TL/gece", 2200, 3200, "FIN-POL-007"),
                ("Özel araç kilometre ücreti", "TL/km", 6.8, 9.5, "FIN-POL-007"),
                ("Planlanan yurt içi seyahat", "adet", 410, 520, "Departman planları"),
                ("Planlanan yurt dışı seyahat", "adet", 64, 118, "Departman planları"),
                ("Toplam seyahat bütçesi", "milyon TL", 6.9, 12.4, "Departman planları"),
            ),
            title="Seyahat Bütçesi Varsayımları",
            notes=(
                "Yurt dışı seyahat artışının büyük bölümü Berlin ofisi (Nebula Technology GmbH) ve DACH satış faaliyetlerinden kaynaklanır.",
            ),
        ),
        Sheet(
            "Onay",
            ("Adım", "Ad Soyad / Kurul", "Unvan", "Tarih", "Açıklama"),
            (
                ("Hazırlayan", "Tolga Yıldırım", "Finans Analisti", "28.11.2025", "Taslak v1.0"),
                (
                    "Kontrol",
                    "Buse Erdoğan",
                    "Mali Müşavir",
                    "03.12.2025",
                    "Vergi ve bordro varsayımları",
                ),
                ("Uygun görüş", "Ali Vural", "Finans Müdürü", "05.12.2025", "Sürüm 1.1"),
                ("Uygun görüş", "Mehmet Yılmaz", "CEO", "10.12.2025", "Sürüm 1.2"),
                ("Onay", "Yönetim Kurulu", "", "18.12.2025", "Karar No 2025/09"),
            ),
            title="Onay Kaydı",
            notes=(
                "Bütçe revizyonları yalnızca Yönetim Kurulu kararıyla yapılabilir; departmanlar arası aktarım limiti yıllık bütçenin %5'idir.",
            ),
        ),
    ),
)

PURCHASING = Doc(
    path="finans/Satin_Alma_ve_Onay_Yetkileri_Proseduru.docx",
    title="Satın Alma ve Onay Yetkileri Prosedürü",
    lang="tr",
    date=D(2026, 2, 1),
    doc_no="FIN-PRO-002",
    meta=(
        ("Sürüm", "3.0"),
        ("Sahibi", "Ali Vural, Finans Müdürü"),
        ("Onaylayan", "Mehmet Yılmaz, CEO"),
        ("Yürürlük", "1 Şubat 2026"),
    ),
    blocks=(
        H1("1. Amaç"),
        P(
            "Bu prosedür, Nebula Teknoloji A.Ş.'nin mal ve hizmet alımlarında kimin hangi tutara kadar "
            "onay verebileceğini, teklif toplama kurallarını ve tedarikçi seçiminde uyulacak kontrolleri "
            "tanımlar. Amaç, harcamaların bütçe ile uyumlu, şeffaf ve denetlenebilir şekilde yapılmasıdır."
        ),
        H1("2. Kapsam"),
        P(
            "Prosedür, Türkiye'deki tüm ofisleri (İstanbul, Ankara, İzmir) ve tüm departmanları kapsar. "
            "Berlin ofisi alımları Nebula Technology GmbH'nin yerel imza yetkileri çerçevesinde yapılır; "
            "ancak 25.000 EUR üzerindeki alımlar için Finans Müdürlüğü'nün yazılı uygun görüşü alınır. "
            "Personel giderleri, vergi ödemeleri ve kira gibi sözleşmeye bağlı düzenli ödemeler bu "
            "prosedürün kapsamı dışındadır."
        ),
        H1("3. Tanımlar"),
        UL(
            "Talep eden: İhtiyacı tanımlayan ve satın alma talebini sisteme giren çalışan.",
            "Bütçe sahibi: İlgili departman bütçesinden sorumlu departman yöneticisi.",
            "Satın Alma Komitesi: Yüksek tutarlı alımları değerlendiren, bu prosedürün 6. maddesinde tanımlanan kurul.",
            "Tutar: Sözleşme süresi boyunca ödenecek toplam bedel, KDV hariç. Çok yıllı sözleşmelerde toplam taahhüt esas alınır.",
        ),
        H1("4. Genel ilkeler"),
        UL(
            "Her alım onaylı 2026 bütçesinde karşılığı olan bir kalem üzerinden yapılır; bütçe dışı alımlar CEO onayı gerektirir.",
            "Onay, sipariş verilmeden ve sözleşme imzalanmadan önce alınır. Geriye dönük onay yalnızca 8. maddedeki acil alımlar için mümkündür.",
            "Bir alımı onay sınırlarının altında kalacak şekilde parçalara bölmek yasaktır ve disiplin konusudur.",
            "Talep eden kişi, kendi talebini onaylayamaz; onay her zaman bir üst yetki seviyesindeki kişi tarafından verilir.",
        ),
        H1("5. Onay yetki matrisi"),
        P(
            "Onay makamı, alımın KDV hariç toplam tutarına göre belirlenir. Aşağıdaki matris 1 Şubat 2026 "
            "itibarıyla geçerlidir ve bir önceki sürümdeki (v2.1) eşiklerin yerini almıştır."
        ),
        T(
            ("Tutar aralığı (KDV hariç)", "Onay makamı", "Teklif şartı", "Ek koşul"),
            (
                ("0 – 25.000 TL", "Departman yöneticisi", "En az 1 teklif", "—"),
                (
                    "25.001 – 250.000 TL",
                    "Finans Müdürü (Ali Vural)",
                    "100.000 TL ve üzeri için 3 yazılı teklif",
                    "Bütçe kontrolü",
                ),
                (
                    "250.001 – 1.000.000 TL",
                    "CEO (Mehmet Yılmaz)",
                    "En az 3 yazılı teklif",
                    "500.000 TL ve üzeri için Satın Alma Komitesi",
                ),
                (
                    "1.000.000 TL üzeri",
                    "Yönetim Kurulu",
                    "En az 3 yazılı teklif",
                    "Satın Alma Komitesi raporu zorunlu",
                ),
            ),
        ),
        P(
            "100.000 TL ve üzerindeki her alım için en az 3 yazılı teklif alınması zorunludur. Pazarda tek "
            "tedarikçi bulunması hâlinde (örneğin mevcut bir yazılımın lisans yenilemesi) gerekçe yazılı "
            "olarak talebe eklenir ve Finans Müdürü tarafından onaylanır."
        ),
        H1("6. Satın Alma Komitesi"),
        P(
            "500.000 TL ve üzerindeki alımlar, onay makamına sunulmadan önce Satın Alma Komitesi'nde "
            "değerlendirilir. Komite Finans Müdürü Ali Vural başkanlığında BT Müdürü Emre Kaya, Hukuk ve "
            "Uyum Müdürü Elif Aydın ve talep eden departmanın yöneticisinden oluşur. Komite iki haftada bir "
            "çarşamba günü toplanır; acil durumlarda başkanın çağrısıyla olağanüstü toplanabilir."
        ),
        P(
            "Komite, teklifleri fiyat (%40), teknik uygunluk (%30), bilgi güvenliği ve KVKK uyumu (%20) ve "
            "tedarikçinin finansal sağlamlığı (%10) ağırlıklarıyla puanlar. Değerlendirme raporu onay "
            "makamına sunulan dosyanın zorunlu ekidir."
        ),
        H1("7. Tedarikçi seçimi ve değerlendirme"),
        UL(
            "Kişisel veri işleyecek her tedarikçi, sipariş öncesinde Hukuk ve Uyum Müdürlüğü'nün KVKK ve bilgi güvenliği değerlendirme anketini doldurur. Anket sonuçları 10 iş günü içinde değerlendirilir.",
            "Bulut veya yazılım hizmeti sağlayan tedarikçiler için BT Müdürlüğü'nün teknik uygunluk onayı ayrıca alınır.",
            "Yeni tedarikçi kaydı için vergi levhası, imza sirküleri ve banka hesap teyit yazısı istenir.",
            "Yıllık alım hacmi 1.000.000 TL'yi aşan tedarikçiler her yıl Ocak ayında performans değerlendirmesine tabi tutulur.",
        ),
        H1("8. Acil alımlar"),
        P(
            "Hizmet kesintisi veya güvenlik olayı gibi gecikmenin şirkete zarar vereceği durumlarda, "
            "150.000 TL'ye kadar olan alımlar BT Müdürü veya ilgili departman yöneticisinin onayıyla "
            "yapılabilir. Bu alımların normal onay makamından 3 iş günü içinde geriye dönük onay alması "
            "zorunludur. Acil alım gerekçesi olay kaydı numarasıyla birlikte talebe eklenir."
        ),
        H1("9. Sipariş, sözleşme ve ödeme"),
        UL(
            "Onaylanan talepler için Finans tarafından SA-2026-0001 biçiminde numaralandırılmış satın alma siparişi düzenlenir.",
            "Standart tedarikçi ödeme vadesi fatura tarihinden itibaren 45 gündür. KOBİ statüsündeki tedarikçilere 30 gün vade uygulanır.",
            "Faturanın 10 gün içinde ödenmesi karşılığında %2 erken ödeme iskontosu önerilebilir; karar Finans Müdürü'ne aittir.",
            "Ödemeler haftada bir, perşembe günleri toplu olarak yapılır.",
        ),
        H1("10. Yazılım ve SaaS abonelikleri"),
        P(
            "Tutarından bağımsız olarak tüm yazılım ve SaaS abonelikleri BT Müdürlüğü'nün onayından geçer ve "
            "BT varlık envanterine kaydedilir. Kurumsal kartla bireysel abonelik başlatılması yasaktır. "
            "Otomatik yenilenen aboneliklerin sahibi, yenileme tarihinden en az 30 gün önce kullanım "
            "gözden geçirmesi yapar."
        ),
        H1("11. Raporlama ve denetim"),
        P(
            "Finans Analisti Tolga Yıldırım, her ayın ilk haftasında bir önceki ayın onay matrisi uyum "
            "raporunu hazırlar. Rapor; onaysız siparişleri, bölünmüş alım şüphesi taşıyan işlemleri ve "
            "geriye dönük acil alım onaylarını içerir ve Denetim Komitesi Başkanı Dr. Levent Sarıgül'e "
            "üç ayda bir sunulur."
        ),
        H1("12. Sürüm geçmişi"),
        T(
            ("Sürüm", "Tarih", "Değişiklik"),
            (
                ("2.1", "01.03.2025", "Eşikler: 20.000 / 200.000 / 750.000 TL"),
                ("3.0", "01.02.2026", "Eşikler: 25.000 / 250.000 / 1.000.000 TL"),
            ),
        ),
        P(
            "Sürüm 2.1'de departman yöneticisi onay sınırı 20.000 TL, Finans Müdürü sınırı 200.000 TL ve CEO "
            "sınırı 750.000 TL idi; 750.000 TL üzerindeki alımlar Yönetim Kurulu onayına gidiyordu. Bu "
            "eşikler 1 Şubat 2026 itibarıyla geçerliliğini yitirmiştir."
        ),
    ),
)

TRAVEL = Doc(
    path="finans/Seyahat_ve_Harcama_Politikasi_2026.pdf",
    title="Seyahat ve Harcama Politikası",
    subtitle="Yurt içi ve yurt dışı iş seyahatleri, harcırah ve masraf bildirimi",
    lang="tr",
    date=D(2026, 1, 26),
    doc_no="FIN-POL-007",
    meta=(
        ("Sürüm", "4.0"),
        ("Sahibi", "Ali Vural, Finans Müdürü"),
        ("Onaylayan", "Mehmet Yılmaz, CEO"),
        ("Yürürlük", "1 Şubat 2026"),
    ),
    blocks=(
        H1("1. Amaç ve kapsam"),
        P(
            "Bu politika, Nebula Teknoloji A.Ş. çalışanlarının şirket adına yaptığı iş seyahatlerinin "
            "planlanması, onaylanması ve masraflarının geri ödenmesine ilişkin kuralları belirler. "
            "Politika tüm Türkiye ofislerindeki çalışanları ve şirket adına seyahat eden danışmanları "
            "kapsar. Berlin ofisi çalışanlarının Almanya içi seyahatleri Nebula Technology GmbH'nin yerel "
            "kurallarına tabidir; Türkiye'ye yapılan seyahatlerde bu politika uygulanır."
        ),
        H1("2. Seyahat onayı"),
        UL(
            "Yurt içi seyahatler, seyahatten en az 5 iş günü önce departman yöneticisi tarafından onaylanır.",
            "Yurt dışı seyahatler, en az 15 iş günü önce departman yöneticisi ve Finans Müdürü tarafından onaylanır.",
            "Onaysız başlatılan seyahatlerin masrafları geri ödenmez.",
            "Seyahat talepleri, tahmini maliyet ve iş gerekçesiyle birlikte masraf yönetim sistemine girilir.",
        ),
        H1("3. Ulaşım"),
        P(
            "Uçak biletleri ekonomi sınıfında ve en az 7 gün önceden alınır. Uçuş süresi 6 saati aşan "
            "seyahatlerde business sınıfı yalnızca CEO onayıyla kullanılabilir. Bagaj ücretleri, iş için "
            "zorunlu ekipman taşındığında karşılanır. Şehirlerarası 400 km'nin altındaki mesafelerde "
            "öncelikle tren veya otobüs tercih edilir."
        ),
        P(
            "Taksi kullanımı havalimanı transferleri, saat 22:00'den sonraki dönüşler ve toplu taşımanın "
            "bulunmadığı güzergâhlar için serbesttir. Kiralık araçlarda kompakt sınıf esastır. Kişisel "
            "aracını iş için kullanan çalışana kilometre başına 9,5 TL ödenir; köprü ve otoyol ücretleri "
            "ayrıca karşılanır."
        ),
        H1("4. Konaklama"),
        P(
            "Konaklama, şirketin anlaşmalı otellerinde veya aşağıdaki gecelik üst limitleri aşmayacak "
            "şekilde yapılır. Limitler kahvaltı dahil, KDV dahil oda fiyatı için geçerlidir. Fuar ve büyük "
            "etkinlik dönemlerinde limit aşımı Finans Müdürü onayıyla kabul edilir."
        ),
        T(
            ("Konum", "Gecelik üst limit"),
            (
                ("İstanbul", "4.500 TL"),
                ("Diğer şehirler (Türkiye)", "3.200 TL"),
                ("Almanya", "165 EUR"),
                ("Diğer Avrupa ülkeleri", "140 EUR"),
                ("Avrupa dışı", "175 USD"),
            ),
            widths=(2.2, 1.4),
        ),
        H1("5. Harcırah"),
        P(
            "Harcırah; yemek, şehir içi küçük ulaşım ve bahşiş gibi belgelendirilmesi güç günlük "
            "giderleri karşılar. 2026 yılında yurt içi harcırah günlük 1.400 TL, yurt dışı harcırah "
            "günlük 95 EUR'dur. Harcırah tutarları her yıl Finans Müdürlüğü tarafından bütçe "
            "hazırlığında gözden geçirilir."
        ),
        UL(
            "Seyahat günü saat 14:00'ten sonra başlıyorsa veya dönüş saat 12:00'den önce tamamlanıyorsa o gün için harcırahın %50'si ödenir.",
            "Konaklamaya kahvaltı dışında öğle veya akşam yemeği dahilse harcırah %30 azaltılır.",
            "Müşteri veya iş ortağı tarafından yemeğin karşılandığı günlerde ilgili öğün için harcırah talep edilmez.",
        ),
        H1("6. Temsil ve ağırlama"),
        P(
            "Müşteri ağırlama giderleri kişi başı 1.750 TL'yi aşamaz ve harcama belgesinde katılımcıların "
            "adı ile kurum bilgisi yer alır. Kamu görevlilerine yönelik ağırlamalar önceden Hukuk ve Uyum "
            "Müdürlüğü'ne bildirilir. Hediye ve ağırlama kabulüne ilişkin sınırlar Etik Kurallar ve İhbar "
            "Prosedürü'nde düzenlenmiştir."
        ),
        H1("7. Masraf bildirimi ve geri ödeme"),
        UL(
            "Masraflar, seyahatin bitiminden itibaren en geç 30 gün içinde belgeleriyle birlikte masraf yönetim sistemine girilir.",
            "60 günden sonra bildirilen masraflar geri ödenmez.",
            "Onaylanan masraflar takip eden ilk bordro döneminde ödenir.",
            "Kurumsal kredi kartı harcamaları da aynı süre içinde belgelendirilir; belgelendirilmeyen tutarlar bordrodan mahsup edilir.",
            "Döviz cinsinden harcamalar, harcama tarihindeki Merkez Bankası döviz satış kuru ile TL'ye çevrilir.",
        ),
        H1("8. 2025 → 2026 değişiklik özeti"),
        P(
            "Sürüm 4.0 ile aşağıdaki limitler güncellenmiştir. Sürüm 3.2'deki (2025) değerler 31 Ocak 2026 "
            "tarihine kadar yapılan seyahatlere uygulanır."
        ),
        T(
            ("Kalem", "2025 (v3.2)", "2026 (v4.0)"),
            (
                ("Yurt içi harcırah", "950 TL/gün", "1.400 TL/gün"),
                ("Yurt dışı harcırah", "80 EUR/gün", "95 EUR/gün"),
                ("Otel limiti İstanbul", "3.100 TL", "4.500 TL"),
                ("Otel limiti diğer şehirler", "2.200 TL", "3.200 TL"),
                ("Kilometre ücreti", "6,8 TL/km", "9,5 TL/km"),
                ("Masraf bildirim süresi", "45 gün", "30 gün"),
            ),
            widths=(2.2, 1.4, 1.4),
        ),
        H1("9. Vize, sigorta ve sağlık"),
        P(
            "Yurt dışı seyahatlerde vize ücretleri ve zorunlu seyahat sağlık sigortası şirket tarafından "
            "karşılanır. Schengen vizesi gerektiren seyahatlerde başvuru, seyahat tarihinden en az 30 gün "
            "önce İK'nın davet mektubu desteğiyle yapılır. Çok girişli vize alınması, yılda 3'ten fazla yurt "
            "dışı seyahati planlanan çalışanlar için önerilir. Seyahat sırasında yaşanan sağlık sorunları "
            "ve güvenlik olayları 24 saat içinde yöneticiye ve İK'ya bildirilir."
        ),
        H1("10. İletişim"),
        P(
            "Politika ile ilgili sorular için Finans Müdürlüğü'ne finans@nebulacrm.example adresinden "
            "ulaşılabilir. Masraf sistemiyle ilgili teknik sorunlar BT yardım masasına iletilir."
        ),
    ),
)

RESULTS = Doc(
    path="finans/Finansal_Sonuclar_2026_Q3.pdf",
    title="2026 Üçüncü Çeyrek Finansal Sonuçlar Raporu",
    subtitle="Yönetim raporu — bağımsız denetimden geçmemiştir",
    lang="tr",
    date=D(2026, 10, 20),
    doc_no="FIN-RAP-2026-Q3",
    classification="Gizli",
    meta=(
        ("Hazırlayan", "Tolga Yıldırım, Finans Analisti"),
        ("Gözden geçiren", "Ali Vural, Finans Müdürü"),
        ("Dağıtım", "Yönetim Kurulu, CEO, departman yöneticileri"),
    ),
    blocks=(
        H1("1. Yönetici özeti"),
        P(
            "Nebula Teknoloji A.Ş. 2026 yılının üçüncü çeyreğini 198,4 milyon TL gelirle kapatmıştır. "
            "Çeyrek geliri bir önceki çeyreğe göre %12,6 artmıştır. Yılın ilk dokuz ayında elde edilen "
            "536,9 milyon TL gelir, aynı dönem bütçesi olan 541,0 milyon TL'nin %99,2'sine karşılık "
            "gelmektedir. Brüt kâr marjı %73,6 ile bütçe varsayımı olan %73,0'ün üzerinde gerçekleşmiştir."
        ),
        P(
            "Üçüncü çeyrek FAVÖK'ü 27,8 milyon TL, FAVÖK marjı %14,0 olmuştur. 30 Eylül 2026 itibarıyla "
            "nakit ve nakit benzerleri 612,5 milyon TL'dir. Alacak tahsil süresi (DSO) ikinci çeyrekteki "
            "52 günden 47 güne gerilemiştir."
        ),
        H1("2. Gelir tablosu özeti"),
        P("Tablodaki tutarlar milyon TL'dir; marjlar gelirin yüzdesi olarak verilmiştir."),
        T(
            ("Kalem", "2Ç 2026", "3Ç 2026", "9A 2026", "9A Bütçe"),
            (
                ("Gelir", "176,2", "198,4", "536,9", "541,0"),
                ("Satışların maliyeti", "48,6", "52,4", "146,8", "146,1"),
                ("Brüt kâr", "127,6", "146,0", "390,1", "394,9"),
                ("Brüt kâr marjı", "%72,4", "%73,6", "%72,7", "%73,0"),
                ("Faaliyet giderleri", "106,3", "118,2", "325,8", "324,8"),
                ("FAVÖK", "21,3", "27,8", "64,3", "70,1"),
                ("FAVÖK marjı", "%12,1", "%14,0", "%12,0", "%13,0"),
                ("Net dönem kârı", "13,9", "19,6", "41,8", "46,5"),
            ),
            widths=(2.4, 1, 1, 1, 1),
        ),
        P("Birinci çeyrek geliri 162,3 milyon TL ve FAVÖK'ü 15,2 milyon TL olarak gerçekleşmişti."),
        H1("3. Gelir kırılımı"),
        UL(
            "Abonelik gelirleri üçüncü çeyrek gelirinin %91,2'sini oluşturmuştur.",
            "Profesyonel hizmetler (kurulum, veri taşıma, eğitim) gelirin %6,4'ünü, diğer gelirler %2,4'ünü oluşturmuştur.",
            "Yurt dışı gelirin payı üçüncü çeyrekte %5,8'dir; 2026 yıl sonu hedefi %6'dır. Almanya'daki müşteri sayısı 30 Eylül 2026 itibarıyla 37'ye ulaşmıştır.",
            "Toplam ödeme yapan müşteri sayısı 30 Eylül 2026 itibarıyla 1.412'dir (30 Haziran 2026: 1.326).",
        ),
        H1("4. Faaliyet giderleri"),
        P(
            "Üçüncü çeyrek faaliyet giderleri 118,2 milyon TL ile bir önceki çeyreğe göre %11,2 artmıştır. "
            "Artışın başlıca nedenleri Temmuz ayında yapılan %11 ara ücret düzenlemesi, Nebula Assist "
            "lansmanına bağlı pazarlama harcamaları ve Berlin ofisindeki satış ekibinin genişlemesidir. "
            "Dokuz aylık faaliyet giderleri bütçenin 1,0 milyon TL üzerindedir."
        ),
        P(
            "Nisan ayında yaşanan INC-2026-0417 kesintisi nedeniyle müşterilere tanınan 1,24 milyon TL "
            "hizmet kredisi, ikinci çeyrek gelirinden indirim olarak kaydedilmiştir."
        ),
        H1("5. Nakit ve işletme sermayesi"),
        T(
            ("Gösterge", "30.06.2026", "30.09.2026"),
            (
                ("Nakit ve nakit benzerleri", "571,3 milyon TL", "612,5 milyon TL"),
                ("Ticari alacaklar", "101,8 milyon TL", "104,6 milyon TL"),
                ("Alacak tahsil süresi (DSO)", "52 gün", "47 gün"),
                ("Ticari borç ödeme süresi", "43 gün", "45 gün"),
            ),
            widths=(2.4, 1.5, 1.5),
        ),
        P(
            "Üçüncü çeyrekte işletme faaliyetlerinden 58,9 milyon TL nakit girişi sağlanmış, 17,7 milyon TL "
            "yatırım harcaması yapılmıştır. Çeyrek ortalama kuru 41,3 TL/USD olarak gerçekleşmiştir; "
            "bütçe varsayımı yıllık ortalama 42,5 TL/USD'dir."
        ),
        H1("6. Bütçe sapması ve yıl sonu tahmini"),
        P(
            "Dokuz aylık gelir bütçenin 4,1 milyon TL altında kalmıştır. Sapmanın yaklaşık 2,6 milyon TL'si "
            "Berlin ofisinde yeni müşteri kazanımının planlanandan yavaş ilerlemesinden, kalan kısmı ise "
            "Nisan kesintisine bağlı hizmet kredilerinden kaynaklanmaktadır."
        ),
        P(
            "Finans Müdürlüğü'nün güncel yıl sonu tahmini 738,5 milyon TL gelir ve %13,6 FAVÖK marjıdır. "
            "Bu tahmin, 742,0 milyon TL'lik yıllık gelir bütçesinin %99,5'ine karşılık gelir. Dördüncü "
            "çeyrekte 15 Eylül 2026'da genel kullanıma açılan Nebula Assist'in Profesyonel plan ek modül "
            "satışlarının gelire katkısı ilk kez tam çeyrek olarak görülecektir."
        ),
        H1("7. Departman bazında bütçe kullanımı"),
        P(
            "Dokuz aylık departman harcamalarının yıllık bütçeye oranı aşağıdadır. Doğrusal kullanım "
            "beklentisi Eylül sonu için %75'tir."
        ),
        T(
            ("Departman", "9A harcama", "Yıllık bütçe", "Kullanım"),
            (
                ("Ar-Ge", "124,9", "168,4", "%74,2"),
                ("Pazarlama ve Satış", "75,1", "96,7", "%77,7"),
                ("Bilgi Teknolojileri", "29,6", "41,2", "%71,8"),
                ("Müşteri Deneyimi", "28,4", "38,9", "%73,0"),
                ("Diğer departmanlar", "53,9", "71,7", "%75,2"),
            ),
            widths=(2.2, 1.1, 1.1, 1.0),
        ),
        P(
            "Pazarlama ve Satış'taki doğrusal kullanım üzerindeki harcama, Eylül ayındaki Nebula Assist "
            "lansman kampanyasından kaynaklanmaktadır ve yıl sonunda bütçe içinde kalması beklenmektedir. "
            "Tablo dağıtılmamış ortak giderleri içermez; kira, sigorta ve danışmanlıktan oluşan ortak "
            "giderler dokuz ayda 13,9 milyon TL olmuştur."
        ),
        H1("8. Riskler"),
        UL(
            "Kur riski: Giderlerin yaklaşık %18'i döviz cinsindendir (lisanslar, Berlin ofisi, FRA-1 bölgesi).",
            "Tahsilat riski: 90 günü aşan alacaklar toplam alacakların %4,3'üdür (30.06.2026: %5,1).",
            "Ücret enflasyonu: 2027 bütçesinde personel giderleri için ilk varsayım %38 artıştır.",
        ),
    ),
)

DOCS = [BUDGET, PURCHASING, TRAVEL, RESULTS]
