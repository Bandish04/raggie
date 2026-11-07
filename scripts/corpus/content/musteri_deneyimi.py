# SPDX-License-Identifier: Apache-2.0

"""Müşteri Deneyimi: SLA matrix, support handbook, Q3 satisfaction report, H1 churn analysis."""

from model import H1, H2, OL, UL, D, Doc, P, Sheet, T

SLA_MATRIX = Doc(
    path="musteri-deneyimi/Destek_SLA_Matrisi_2026.xlsx",
    title="NebulaCRM Destek SLA Matrisi 2026",
    lang="tr",
    date=D(2026, 1, 1),
    doc_no="MD-SLA-2026",
    sheets=(
        Sheet(
            name="Sürüm Bilgisi",
            title="NebulaCRM Destek SLA Matrisi 2026",
            header=("Alan", "Değer"),
            rows=(
                ("Doküman No", "MD-SLA-2026"),
                ("Yürürlük tarihi", "01.01.2026"),
                ("Geçerlilik", "01.01.2026 – 31.12.2026"),
                ("Doküman sahibi", "Can Öztürk (Müşteri Deneyimi Müdürü)"),
                ("Onaylayan", "Mehmet Yılmaz (CEO)"),
                ("Hazırlayan", "Derya Kılıç (Destek Uzmanı)"),
                ("Önceki sürüm", "MD-SLA-2025 (31.12.2025 itibarıyla yürürlükten kalktı)"),
                ("Kapsam", "NebulaCRM, NebulaAnalytics ve Nebula Assist için destek taahhütleri"),
                ("Sözleşme dayanağı", "Ana Hizmet Sözleşmesi Ek-2 (Hizmet Seviyesi Eki)"),
                ("İletişim", "destek@nebulacrm.example"),
            ),
            widths=(26, 70),
        ),
        Sheet(
            name="İlk Yanıt Süreleri",
            title="İlk yanıt süresi hedefleri (talebin kaydından ilk insan yanıtına kadar)",
            header=("Plan", "P1 – Kritik", "P2 – Yüksek", "P3 – Normal", "P4 – Düşük"),
            rows=(
                ("Başlangıç", "8 iş saati", "2 iş günü", "3 iş günü", "5 iş günü"),
                ("Profesyonel", "2 saat", "8 iş saati", "2 iş günü", "5 iş günü"),
                ("Kurumsal", "30 dakika", "4 saat", "1 iş günü", "3 iş günü"),
                ("Kurumsal Plus", "15 dakika", "2 saat", "8 iş saati", "2 iş günü"),
            ),
            notes=(
                "İş saati/iş günü, planın destek saatleri içinde sayılır (bkz. Destek Saatleri ve Kanallar).",
                "Kurumsal ve Kurumsal Plus planlarında P1 süresi 7/24 işler; diğer öncelikler iş saatlerine bağlıdır.",
                "Otomatik yanıt e-postaları ilk yanıt sayılmaz; ilk yanıt destek uzmanının vakaya özel ilk mesajıdır.",
                "2025 matrisinde Kurumsal P1 ilk yanıt hedefi 1 saat idi; 2026 matrisinde 30 dakikaya indirildi.",
                "2025 matrisinde Kurumsal Plus P2 ilk yanıt hedefi 3 saat idi; 2026 matrisinde 2 saate indirildi.",
            ),
            widths=(18, 16, 16, 16, 16),
        ),
        Sheet(
            name="Çözüm Hedefleri",
            title="Çözüm veya kalıcı geçici çözüm hedefleri ile P1 güncelleme sıklığı",
            header=(
                "Plan",
                "P1 çözüm hedefi",
                "P2 çözüm hedefi",
                "P3 çözüm hedefi",
                "P4 çözüm hedefi",
                "P1 durum güncelleme sıklığı",
            ),
            rows=(
                ("Başlangıç", "2 iş günü", "5 iş günü", "10 iş günü", "Sonraki sürüm", "1 iş günü"),
                ("Profesyonel", "1 iş günü", "3 iş günü", "7 iş günü", "Sonraki sürüm", "4 saat"),
                ("Kurumsal", "8 saat", "2 iş günü", "5 iş günü", "Sonraki sürüm", "60 dakika"),
                ("Kurumsal Plus", "4 saat", "1 iş günü", "3 iş günü", "Sonraki sürüm", "30 dakika"),
            ),
            notes=(
                "Çözüm hedefleri taahhüt değil, iç hedeftir; hizmet kredisi yalnızca erişilebilirlik taahhüdüne bağlıdır.",
                "Müşteriden bilgi beklenen süre (Müşteri Yanıtı Bekleniyor durumu) çözüm süresinden düşülür.",
                "Kod düzeltmesi gerektiren P3/P4 talepler ürün yol haritasına alınır ve sürüm notlarında duyurulur.",
            ),
            widths=(18, 16, 16, 16, 16, 24),
        ),
        Sheet(
            name="Erişilebilirlik ve Kredi",
            title="Aylık erişilebilirlik taahhüdü ve hizmet kredisi kademeleri",
            header=(
                "Plan",
                "Aylık erişilebilirlik aralığı",
                "Hizmet kredisi (aylık ücretin yüzdesi)",
                "Açıklama",
            ),
            rows=(
                (
                    "Başlangıç",
                    "Taahhüt yok (hedef %99,5)",
                    "Uygulanmaz",
                    "En iyi gayret esasıyla işletilir",
                ),
                ("Profesyonel", "%99,5 altı", "%10", "Profesyonel planda azami kredi oranı"),
                ("Kurumsal", "%99,9 altı – %99,0 ve üzeri", "%10", "Kurumsal taahhüt: %99,9"),
                ("Kurumsal", "%99,0 altı – %95,0 ve üzeri", "%25", ""),
                ("Kurumsal", "%95,0 altı", "%50", "Azami kredi oranı"),
                (
                    "Kurumsal Plus",
                    "%99,95 altı – %99,9 ve üzeri",
                    "%5",
                    "Kurumsal Plus taahhüt: %99,95",
                ),
                ("Kurumsal Plus", "%99,9 altı – %99,0 ve üzeri", "%10", ""),
                ("Kurumsal Plus", "%99,0 altı – %95,0 ve üzeri", "%25", ""),
                ("Kurumsal Plus", "%95,0 altı", "%50", "Azami kredi oranı"),
            ),
            notes=(
                "Erişilebilirlik, planlı bakım hariç olmak üzere takvim ayı bazında üretim API ve web uygulaması üzerinden ölçülür.",
                "Planlı bakım penceresi: Pazar 02:00–05:00 (TSİ), ayda en fazla 4 saat; en az 5 iş günü önceden duyurulur.",
                "Hizmet kredisi, ilgili ayın bitiminden itibaren 30 gün içinde destek@nebulacrm.example adresine yazılı talep ile istenmelidir.",
                "Kredi bir sonraki faturadan düşülür; nakit iade yapılmaz.",
            ),
            widths=(18, 32, 34, 34),
        ),
        Sheet(
            name="Destek Saatleri ve Kanallar",
            title="Plan bazında destek saatleri, kanallar ve hesap yönetimi",
            header=("Plan", "Destek saatleri", "Kanallar", "P1 için 7/24", "Hesap yönetimi"),
            rows=(
                ("Başlangıç", "Hafta içi 09:00–18:00", "E-posta", "Hayır", "Yok"),
                ("Profesyonel", "Hafta içi 08:00–20:00", "E-posta, telefon", "Hayır", "Yok"),
                (
                    "Kurumsal",
                    "Hafta içi 08:00–20:00",
                    "E-posta, telefon, uygulama içi sohbet",
                    "Evet",
                    "Atanmış Müşteri Başarı Uzmanı",
                ),
                (
                    "Kurumsal Plus",
                    "7/24 (tüm öncelikler)",
                    "E-posta, telefon, uygulama içi sohbet, özel kanal",
                    "Evet",
                    "İsimli Teknik Hesap Yöneticisi (TAM)",
                ),
            ),
            notes=(
                "Saatler Türkiye saatidir (TSİ). Resmî tatillerde yalnızca 7/24 kapsamındaki talepler işlenir.",
                "DACH müşterilerine Almanca destek, Nebula Technology GmbH tarafından hafta içi 09:00–17:00 (CET) verilir.",
            ),
            widths=(18, 26, 46, 14, 36),
        ),
    ),
)

HANDBOOK = Doc(
    path="musteri-deneyimi/Musteri_Destek_El_Kitabi.md",
    title="Müşteri Destek El Kitabı",
    subtitle="Destek ekibi için kanallar, önceliklendirme, kademeler ve eskalasyon kuralları",
    lang="tr",
    date=D(2026, 3, 2),
    doc_no="MD-REH-001",
    meta=(
        ("Sürüm", "5.0"),
        ("Sahibi", "Can Öztürk (Müşteri Deneyimi Müdürü)"),
        ("Hazırlayan", "Derya Kılıç (Destek Uzmanı)"),
        ("Yürürlük", "02.03.2026"),
    ),
    blocks=(
        H1("1. Amaç ve kapsam"),
        P(
            "Bu el kitabı, NebulaCRM müşterilerinden gelen destek taleplerinin nasıl karşılandığını, "
            "önceliklendirildiğini ve gerektiğinde nasıl eskale edildiğini tanımlar. İzmir Müşteri Destek "
            "Merkezi'ndeki L1 ekibi, İstanbul'daki L2 ürün uzmanları ve Ar-Ge nöbet ekibi bu kurallara "
            "uyar. Plan bazındaki süre taahhütleri bu dokümanda tekrar edilmez; güncel değerler için "
            "Destek SLA Matrisi 2026 dosyası esas alınır."
        ),
        P(
            "El kitabı her yıl mart ayında gözden geçirilir. Sürüm 5.0, İzmir merkezinin ilk tam yılı "
            "sonunda toplanan geri bildirimlerle hazırlanmıştır."
        ),
        H1("2. Destek kanalları"),
        UL(
            "E-posta: destek@nebulacrm.example adresine gelen her ileti otomatik olarak destek "
            "platformunda bir talep açar. Tüm planlar için geçerlidir.",
            "Telefon: Profesyonel, Kurumsal ve Kurumsal Plus müşterileri için. Numara müşteri "
            "portalında, hesap yöneticisinin imza bloğunda ve sözleşme ekinde yer alır.",
            "Uygulama içi sohbet: Kurumsal ve Kurumsal Plus planlarında, NebulaCRM arayüzünün sağ alt "
            "köşesindeki yardım düğmesinden açılır. Sohbet 10 dakikadan uzun sürerse talebe dönüştürülür.",
            "Özel kanal: Kurumsal Plus müşterileri için Teknik Hesap Yöneticisi (TAM) ile ortak "
            "mesajlaşma kanalı. Bu kanaldan gelen P1 bildirimleri de mutlaka talebe dönüştürülür.",
            "Durum sayfası: status.nebulacrm.example adresi bakım ve kesinti duyuruları içindir; talep "
            "kabul etmez.",
        ),
        P(
            "Telefonla gelen her görüşme için talep kaydı açmak zorunludur. Kayıt açılmadan verilen "
            "destek SLA ölçümüne girmez ve kalite örneklemesinde görünmez."
        ),
        H1("3. Öncelik tanımları"),
        P(
            "Öncelik, müşterinin seçtiği değere göre değil, aşağıdaki etki tanımlarına göre L1 uzmanı "
            "tarafından belirlenir. Müşteri önceliğe itiraz ederse vaka bir üst kademeye danışılır."
        ),
        T(
            ("Öncelik", "Tanım", "Örnek"),
            (
                (
                    "P1 – Kritik",
                    "Üretim ortamı kullanılamıyor veya veri kaybı riski var",
                    "Tüm kullanıcılar giriş yapamıyor",
                ),
                (
                    "P2 – Yüksek",
                    "Ana iş akışı ciddi biçimde aksıyor, geçici çözüm yok",
                    "Teklif oluşturma tüm ekipte hata veriyor",
                ),
                (
                    "P3 – Normal",
                    "İşlev kısmen etkileniyor, geçici çözüm mevcut",
                    "Tek bir rapor yanlış filtre uyguluyor",
                ),
                (
                    "P4 – Düşük",
                    "Soru, yapılandırma talebi veya iyileştirme önerisi",
                    "Alan etiketinin değiştirilmesi",
                ),
            ),
        ),
        H1("4. Destek kademeleri"),
        H2("4.1 L1 – İzmir Müşteri Destek Merkezi"),
        P(
            "L1 ekibi İzmir Bayraklı'daki merkezde vardiyalı çalışır. Hafta içi gündüz vardiyası "
            "08:00–16:00, akşam vardiyası 12:00–20:00 saatleri arasındadır. Kurumsal ve Kurumsal Plus "
            "P1 talepleri için gece ve hafta sonu nöbeti İzmir ekibinden iki uzmanla tutulur. L1, "
            "taleplerin yaklaşık dörtte üçünü kendi kademesinde çözer; hedef L1 çözüm oranı %75'tir."
        ),
        H2("4.2 L2 – Ürün uzmanları"),
        P(
            "L2 ekibi İstanbul'da çalışan ürün uzmanlarından oluşur. Entegrasyon, raporlama, yetki "
            "yapılandırması ve veri içe aktarma konularında derin bilgiye sahiptir. L2, bir hatanın "
            "yazılım kusuru olduğunu doğruladığında Ar-Ge'ye NCRM önekli bir kusur kaydı açar ve talebi "
            "bu kayda bağlar."
        ),
        H2("4.3 L3 – Ar-Ge nöbet ekibi"),
        P(
            "L3, Ar-Ge'nin haftalık nöbet çizelgesindeki mühendislerden oluşur. L3'e yalnızca L2 "
            "üzerinden ulaşılır; L1'in doğrudan Ar-Ge'yi araması yalnızca ilan edilmiş bir Sev-1 olayında "
            "serbesttir."
        ),
        H1("5. Eskalasyon kuralları"),
        OL(
            "Süre bazlı eskalasyon: P1 talep 45 dakika içinde L1'de çözülemezse L2'ye aktarılır; P2 "
            "talepler için bu süre 4 saattir.",
            "Kusur eskalasyonu: Yazılım kusuru şüphesi olan her talep, L1 tarafından tekrar adımlarıyla "
            "birlikte L2'ye aktarılır. L2 doğrulamadan Ar-Ge'ye kayıt açılmaz.",
            "Yönetim eskalasyonu: Bir Kurumsal veya Kurumsal Plus müşterisi aynı takvim ayında iki SLA "
            "ihlali yaşarsa Can Öztürk bilgilendirilir ve atanmış Müşteri Başarı Uzmanı 1 iş günü içinde "
            "müşteriyle görüşür.",
            "Olay eskalasyonu: Aynı belirtiyle 15 dakika içinde en az 5 farklı müşteriden talep gelirse "
            "vardiya sorumlusu olası bir olay bildirir ve DevOps nöbetçisine haber verir.",
        ),
        P(
            "Sev-1 olarak ilan edilen kesintilerde müşterilere ilk kamuya açık bildirim, olay ilanından "
            "sonra 15 dakika içinde durum sayfasında yayımlanır ve olay sürdükçe her 30 dakikada bir "
            "güncellenir. Olay sonrası müşteri bilgilendirme metni Müşteri Deneyimi ile DevOps tarafından "
            "birlikte onaylanır."
        ),
        H1("6. Talep yaşam döngüsü"),
        UL(
            "Yeni: Talep oluşturuldu, öncelik henüz atanmadı.",
            "Açık: Öncelik atandı, uzman üzerinde çalışıyor.",
            "Müşteri Yanıtı Bekleniyor: Uzman müşteriden bilgi istedi; bu süre çözüm süresinden düşülür.",
            "Ar-Ge'de: Talep bir NCRM kusur kaydına bağlandı.",
            "Çözüldü: Uzman çözümü iletti; müşteri yeniden açabilir.",
            "Kapandı: Talep kapandı; yeniden açılamaz, yeni talep açılır.",
        ),
        P(
            "Müşteri Yanıtı Bekleniyor durumunda kalan talepler için 3. ve 6. günde otomatik hatırlatma "
            "gönderilir; müşteri yanıt vermezse talep 7 gün sonunda otomatik olarak kapanır. Çözüldü "
            "durumundaki talep 72 saat içinde yeniden açılmazsa Kapandı durumuna geçer."
        ),
        P(
            "Talep kapandıktan 1 saat sonra müşteriye 5 puanlık memnuniyet (CSAT) anketi gönderilir. "
            "1 veya 2 puan veren müşteriler için vardiya sorumlusu 2 iş günü içinde geri arama yapar."
        ),
        H1("7. Dil desteği"),
        P(
            "Destek Türkçe ve İngilizce verilir. DACH bölgesindeki müşterilere Almanca destek, Berlin'deki "
            "Nebula Technology GmbH ekibi tarafından hafta içi 09:00–17:00 (CET) saatleri arasında sunulur. "
            "Almanca taleplerde de öncelik tanımları ve eskalasyon kuralları aynen uygulanır."
        ),
        H1("8. Kalite güvencesi"),
        P(
            "Her hafta kapanan taleplerin %5'i rastgele seçilerek kalite formuyla puanlanır. Form; doğru "
            "önceliklendirme, teknik doğruluk, üslup ve kayıt eksiksizliği olmak üzere dört başlıktan "
            "oluşur. Ekip hedefi 100 üzerinden en az 85 puandır. Örneklemeyi Derya Kılıç koordine eder; "
            "sonuçlar aylık ekip toplantısında paylaşılır."
        ),
        P(
            "Müşteri ekran paylaşımlarında kişisel veri görülebileceğinden oturum kayıtları yalnızca "
            "müşteri onayıyla alınır ve KVKK Kişisel Veri Saklama ve İmha Politikası'ndaki sürelere göre "
            "saklanır. Talep notlarına parola, API anahtarı veya kart bilgisi yazılmaz; yanlışlıkla "
            "yazılırsa not derhal maskelenir."
        ),
        H1("9. Sürüm geçmişi"),
        T(
            ("Sürüm", "Tarih", "Değişiklik"),
            (
                ("4.0", "03.03.2025", "Otomatik kapanma süresi 10 gün olarak belirlendi"),
                ("4.1", "01.09.2025", "İzmir L1 merkezi ve vardiya düzeni eklendi"),
                ("5.0", "02.03.2026", "Otomatik kapanma süresi 10 günden 7 güne indirildi"),
                ("5.0", "02.03.2026", "Almanca destek ve özel kanal tanımları eklendi"),
            ),
        ),
    ),
)

SATISFACTION = Doc(
    path="musteri-deneyimi/Musteri_Memnuniyeti_Raporu_2026_Q3.pdf",
    title="Müşteri Memnuniyeti Raporu – 2026 3. Çeyrek",
    subtitle="NPS, CSAT, destek hacmi ve müşteri geri bildirimleri (1 Temmuz – 30 Eylül 2026)",
    lang="tr",
    date=D(2026, 10, 12),
    doc_no="MD-RAP-2026-Q3",
    meta=(
        ("Hazırlayan", "Efe Taş (Müşteri Başarı Uzmanı)"),
        ("Onaylayan", "Can Öztürk (Müşteri Deneyimi Müdürü)"),
        ("Dağıtım", "Yönetim ekibi, Ürün Yönetimi, Ar-Ge"),
    ),
    blocks=(
        H1("1. Yönetici özeti"),
        P(
            "2026'nın üçüncü çeyreğinde Net Tavsiye Skoru (NPS) 44 oldu. Skor, ikinci çeyrekteki 46 "
            "seviyesinin 2 puan altında kalsa da 2025 yılı ortalaması olan 41'in üzerinde seyretmeye devam "
            "etti. Düşüşün ana nedeni, büyük veri hacmiyle çalışan müşterilerin rapor dışa aktarma "
            "işlemlerinde yaşadığı zaman aşımlarıdır. Buna karşın talep sonrası memnuniyet (CSAT) %92,4 ile "
            "yılın en yüksek seviyesine çıktı."
        ),
        P(
            "Çeyrek boyunca 18.640 destek talebi işlendi. Medyan ilk yanıt süresi 38 dakikaya indi; "
            "ilk temasta çözüm oranı %71 oldu. NPS anketine 2.318 yanıt geldi."
        ),
        H1("2. Temel göstergeler"),
        T(
            ("Gösterge", "2026 Q1", "2026 Q2", "2026 Q3"),
            (
                ("NPS", "42", "46", "44"),
                ("CSAT", "%90,3", "%91,1", "%92,4"),
                ("Destek talebi sayısı", "16.480", "17.205", "18.640"),
                ("Medyan ilk yanıt", "44 dakika", "41 dakika", "38 dakika"),
                ("İlk temasta çözüm", "%68", "%70", "%71"),
                ("L1'de çözülen talep", "%72", "%74", "%76"),
                ("NPS anket yanıtı", "2.051", "2.196", "2.318"),
                ("İlk yanıt SLA uyumu", "%96,9", "%97,4", "%97,8"),
            ),
            caption="Tablo 1. Çeyrek bazında müşteri deneyimi göstergeleri.",
            widths=(2.2, 1, 1, 1),
        ),
        P(
            "Üçüncü çeyrek NPS dağılımı: tavsiye edenler %55, pasifler %34, kötüleyenler %11. "
            "Kötüleyen oranı ikinci çeyrekteki %9 seviyesinden yükseldi."
        ),
        H1("3. Plan ve bölge kırılımı"),
        T(
            ("Segment", "Q3 NPS", "Yanıt sayısı"),
            (
                ("Başlangıç", "31", "612"),
                ("Profesyonel", "42", "934"),
                ("Kurumsal", "49", "641"),
                ("Kurumsal Plus", "57", "131"),
                ("DACH (Almanya)", "51", "64"),
            ),
            caption="Tablo 2. Plan ve bölge bazında Q3 NPS. DACH satırı plan satırlarının alt kümesidir.",
            widths=(2, 1, 1),
        ),
        P(
            "Kurumsal Plus müşterilerinde NPS 57 ile en yüksek seviyede. Bu segmentte isimli Teknik Hesap "
            "Yöneticisi uygulaması olumlu yorumların en sık geçen konusu oldu. Başlangıç planında skorun "
            "31'de kalması, yalnızca e-posta kanalıyla verilen destek ve uzun ilk yanıt süreleriyle "
            "ilişkilendirildi. Almanya'daki 37 müşteriden 64 yanıt alındı; DACH NPS'i 51 oldu."
        ),
        H1("4. Müşteri geri bildirimleri"),
        P(
            "Kötüleyen ve pasif müşterilerin açık uçlu yorumları konu bazında sınıflandırıldı. En sık dile "
            "getirilen sorun, rapor dışa aktarma performansı oldu."
        ),
        T(
            ("Konu", "Yorum payı", "Q2 payı"),
            (
                ("Rapor dışa aktarma performansı", "%18", "%11"),
                ("Mobil uygulama senkronizasyonu", "%12", "%13"),
                ("E-posta entegrasyonu gecikmesi", "%9", "%10"),
                ("Fatura ekranının karmaşıklığı", "%7", "%8"),
                ("Telefon santrali entegrasyonu", "%6", "%5"),
            ),
            caption="Tablo 3. Olumsuz yorumların konu dağılımı (birden fazla konu işaretlenebilir).",
            widths=(2.6, 1, 1),
        ),
        P(
            "Dışa aktarma şikâyetleri ağırlıklı olarak 200.000 satırın üzerindeki raporlarda zaman aşımı "
            "yaşayan Kurumsal müşterilerden geldi. Ürün ekibi dışa aktarma altyapısını yeniden yazdı; "
            "iyileştirme 15 Eylül 2026'da yayımlanan v3.4 sürümüyle canlıya alındı. Etkisi dördüncü "
            "çeyrek anketinde ölçülecek."
        ),
        P(
            "Olumlu yorumlarda en sık geçen konular destek ekibinin hızı, Türkçe arayüzün kalitesi ve "
            "çok para birimli teklif özelliği oldu. Nebula Assist'in temmuz ayındaki beta programına "
            "katılan müşterilerin geri bildirimleri ayrı bir raporda Ürün Yönetimi'ne iletildi."
        ),
        H1("5. Destek operasyonu"),
        P(
            "Talep hacmi bir önceki çeyreğe göre %8,3 arttı. Artışın yaklaşık yarısı Eylül ayındaki v3.4 "
            "geçişi sonrasında gelen kullanım sorularından kaynaklandı. İzmir merkezindeki L1 ekibi "
            "taleplerin %76'sını kendi kademesinde çözdü ve %75 hedefini ilk kez aştı."
        ),
        P(
            "Kurumsal P1 taleplerinde ilk yanıt SLA uyumu %98,6 oldu: çeyrekte açılan 143 Kurumsal P1 "
            "talebinin 2'sinde 30 dakikalık hedef aşıldı. Her iki ihlal de 17 Ağustos 2026 gecesi nöbet "
            "devrinde yaşandı; nöbet devir kontrol listesi bu tarihten sonra güncellendi."
        ),
        H1("6. Aksiyonlar ve sorumlular"),
        T(
            ("Aksiyon", "Sorumlu", "Termin"),
            (
                ("Dışa aktarma etkisini ölç", "Efe Taş", "15.12.2026"),
                ("Başlangıç planına sohbet pilotu", "Derya Kılıç", "30.11.2026"),
                ("Mobil senkronizasyon analizi", "İrem Korkmaz", "31.10.2026"),
                ("Kötüleyenlere geri arama", "Can Öztürk", "Sürekli"),
            ),
            widths=(2.4, 1.3, 1),
        ),
        P(
            "Bir sonraki rapor, dördüncü çeyrek verileriyle Ocak 2027'nin ikinci haftasında yayımlanacaktır."
        ),
    ),
)

_REASONS = T(
    ("Primary reason", "Logos", "Share", "Avg. seats"),
    (
        ("Price / budget pressure", "12", "29%", "7"),
        ("Missing integrations", "9", "22%", "18"),
        ("Business closure / M&A", "7", "17%", "11"),
        ("Switched to competitor", "6", "15%", "23"),
        ("Low adoption / product complexity", "5", "12%", "9"),
        ("Support experience", "2", "5%", "6"),
        ("Total", "41", "100%", "12"),
    ),
    caption="Table 1. Primary churn reasons, H1 2026.",
)
_PLANS = T(
    ("Plan", "Churned logos", "Customers at 30 June 2026"),
    (
        ("Başlangıç", "24", "512"),
        ("Profesyonel", "13", "548"),
        ("Kurumsal", "4", "231"),
        ("Kurumsal Plus", "0", "35"),
    ),
    caption="Table 2. Churned logos by plan.",
)
_ACTIONS = T(
    ("Recommendation", "Owner", "Due"),
    (
        ("Ship a native CTI telephony connector", "Merve Doğan", "v3.4 (September 2026)"),
        ("Offer annual prepay at renewal for Başlangıç accounts", "Deniz Koç", "1 September 2026"),
        ("Mandatory 30-day onboarding check-in for new accounts", "Efe Taş", "1 August 2026"),
        ("Review the save-desk health-score threshold monthly", "Can Öztürk", "1 August 2026"),
    ),
    caption="Table 3. Recommended actions.",
)
CHURN = Doc(
    path="musteri-deneyimi/Churn_Analysis_H1_2026.docx",
    title="Customer Churn Analysis – H1 2026",
    subtitle="Why customers left between 1 January and 30 June 2026, and what we are doing about it",
    lang="en",
    date=D(2026, 7, 20),
    doc_no="MD-ANL-2026-H1",
    meta=(
        ("Version", "1.0"),
        ("Authors", "Efe Taş (Customer Success Specialist), Tolga Yıldırım (Financial Analyst)"),
        ("Owner", "Can Öztürk (Customer Experience Manager)"),
        ("Audience", "Executive team, Product Management, Sales"),
    ),
    blocks=(
        H1("1. Summary"),
        P(
            "We lost 41 customer logos in the first half of 2026. The customer base still grew from 1,180 "
            "on 31 December 2025 to 1,326 on 30 June 2026, but every lost logo costs us roughly three "
            "months of new-logo sales effort to replace. Annualised gross logo churn for H1 2026 was 6.9%, "
            "down from 7.8% for full-year 2025."
        ),
        P(
            "Churn remains concentrated in small accounts: 24 of the 41 churned customers were on the "
            "Başlangıç plan and none were on Kurumsal Plus. Price and budget pressure was the most common "
            "reason, followed by missing integrations. Annualised churned ARR was TRY 11.8 million, which "
            "corresponds to gross revenue churn of 5.2%."
        ),
        H1("2. Method"),
        P(
            "The analysis covers every customer whose subscription ended or was not renewed between "
            "1 January and 30 June 2026. Downgrades and seat reductions are excluded; they are tracked "
            "separately in the net revenue retention report. Each churned account was coded with one "
            "primary reason based on the exit interview, the cancellation form and the account notes. "
            "Exit interviews were completed for 29 of the 41 accounts."
        ),
        P(
            "Finance reconciled the churned ARR figures against billing records. Logo counts use the "
            "billing account as the unit, so a customer group with several legal entities counts once."
        ),
        H1("3. Churn reasons"),
        P(
            "Table 1 lists the primary churn reason for each lost logo. Shares are rounded and may not "
            "add up to exactly 100%."
        ),
        _REASONS,
        P(
            "Price and budget pressure (12 logos) clustered in March and April, after the 2026 price list "
            "took effect on 1 January 2026. Most of these customers were small Başlangıç accounts whose "
            "per-user price rose from TRY 520 to TRY 690. Several said they would have stayed on an annual "
            "prepay plan had they known about the 15% discount."
        ),
        P(
            "Missing integrations (9 logos) is the reason we can act on fastest. Among these accounts, the "
            "most frequently cited gap was a native telephony (CTI) connector that logs calls from the "
            "customer's call-centre system directly into NebulaCRM. Accounting-software synchronisation "
            "came second. Three of the nine accounts moved to a competitor that already offered CTI."
        ),
        P(
            "Business closure and M&A (7 logos) are largely outside our control. Two of these were "
            "acquired by groups that run a different CRM centrally."
        ),
        H1("4. Churn by plan and tenure"),
        _PLANS,
        P(
            "Early-life churn is a recurring pattern: 19 of the 41 churned customers (46%) left within "
            "their first 12 months. Most of them never completed onboarding: fewer than 30% of their "
            "licensed users logged in during the final 60 days before cancellation."
        ),
        H1("5. Save desk results"),
        P(
            "The save desk started on 1 March 2026. Accounts with a health score below 40 are flagged "
            "automatically and contacted by a Customer Success Specialist within 5 business days. Between "
            "March and June the save desk contacted 58 at-risk accounts and saved 23 of them. The most "
            "effective interventions were a free onboarding refresh (11 saves) and moving the customer to "
            "annual prepay (7 saves)."
        ),
        P(
            "Retention discounts follow the standard discount authority in the 2026 price list. Save-desk "
            "offers were capped at a 10% discount for six months, so no save required management approval."
        ),
        H1("6. Recommendations"),
        _ACTIONS,
        P(
            "We will repeat this analysis for H2 2026 in January 2027 and add the impact of the save desk "
            "and of the v3.4 release on the churn reasons."
        ),
    ),
)

DOCS = [SLA_MATRIX, HANDBOOK, SATISFACTION, CHURN]
