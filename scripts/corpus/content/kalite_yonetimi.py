# SPDX-License-Identifier: Apache-2.0

"""Kalite Yönetimi (quality management) department documents."""

from model import H1, H2, OL, UL, D, Doc, P, T

ISO_AUDIT = Doc(
    path="kalite-yonetimi/ISO_27001_Gozetim_Denetimi_Raporu_2026.pdf",
    title="ISO/IEC 27001:2022 Gözetim Denetimi Raporu — 2026",
    subtitle="Bilgi Güvenliği Yönetim Sistemi 2. gözetim denetimi: bulgular ve düzeltici faaliyet planı",
    lang="tr",
    date=D(2026, 6, 19),
    doc_no="KAL-DEN-2026-01",
    classification="Gizli",
    meta=(
        ("Sürüm", "1.0"),
        ("Sahibi", "Selin Arslan, Kalite Müdürü"),
        ("Hazırlayan", "Pınar Yalçın, Kalite Uzmanı"),
        ("Dağıtım", "Yönetim Kurulu Denetim Komitesi, CEO, BT Müdürü, Ar-Ge Müdürü"),
    ),
    blocks=(
        H1("1. Özet"),
        P(
            "Nebula Teknoloji A.Ş. Bilgi Güvenliği Yönetim Sistemi (BGYS), 9–11 Haziran 2026 "
            "tarihlerinde Certa Belgelendirme A.Ş. tarafından ISO/IEC 27001:2022 standardına göre "
            "ikinci gözetim denetiminden geçmiştir. Denetim sonucunda büyük uygunsuzluk tespit "
            "edilmemiş, 3 küçük uygunsuzluk ve 4 gözlem raporlanmıştır. Baş denetçi Nihat Karaca, "
            "belgenin sürdürülmesini önermiştir."
        ),
        P(
            "Sertifika 28 Haziran 2024'te verilmiştir ve 27 Haziran 2027 tarihine kadar "
            "geçerlidir. Küçük uygunsuzluklar için düzeltici faaliyetlerin 9 Eylül 2026 tarihine "
            "kadar tamamlanması ve kanıtlarının belgelendirme kuruluşuna gönderilmesi "
            "gerekmektedir. Yeniden belgelendirme denetimi Mayıs 2027'de planlanmıştır."
        ),
        H1("2. Denetim Bilgileri"),
        T(
            ("Alan", "Bilgi"),
            (
                ("Belgelendirme kuruluşu", "Certa Belgelendirme A.Ş."),
                ("Baş denetçi", "Nihat Karaca"),
                ("Denetçi", "Seda Yüce"),
                ("Denetim tarihleri", "9–11 Haziran 2026"),
                ("Denetim süresi", "6 denetçi-gün"),
                ("Denetim türü", "2. gözetim denetimi"),
                ("Önceki denetim", "1. gözetim, Haziran 2025"),
            ),
            widths=(1.2, 2),
        ),
        P(
            "Denetimin ilk iki günü Maslak Genel Merkez'de yerinde, üçüncü günü ise İzmir Müşteri "
            "Destek Merkezi ile uzaktan bağlantı kurularak gerçekleştirilmiştir. Açılış toplantısı "
            "9 Haziran 2026 saat 09:30'da, kapanış toplantısı 11 Haziran 2026 saat 16:00'da "
            "yapılmıştır. Kapanış toplantısına Mehmet Yılmaz, Emre Kaya, Ayşe Demir ve Selin "
            "Arslan katılmıştır."
        ),
        H1("3. Kapsam"),
        P(
            "BGYS kapsamı: NebulaCRM, NebulaAnalytics ve Nebula Assist hizmetlerinin geliştirilmesi, "
            "işletilmesi ve müşteri desteği; İstanbul Genel Merkez, Ankara Ar-Ge Ofisi ve İzmir "
            "Müşteri Destek Merkezi lokasyonları; IST-1 ve ANK-DR1 veri merkezleri. FRA-1 bölgesi "
            "ve Berlin satış ofisi bu denetimde kapsam dışıdır; kapsam genişletme başvurusu "
            "Aralık 2026'da yapılacaktır. Uygulanabilirlik Bildirgesi sürüm 5.2 esas alınmıştır."
        ),
        H1("4. Bulgular"),
        H2("4.1 Küçük Uygunsuzluklar"),
        T(
            ("No", "Madde", "Bulgu", "Sorumlu"),
            (
                ("NC-1", "A.5.18", "Erişim gözden geçirme gecikmesi", "Emre Kaya"),
                ("NC-2", "A.5.21", "Tedarikçi değerlendirmesi eksik", "Onur Aslan"),
                ("NC-3", "A.5.30", "DR test kaydı imzasız", "Emre Kaya"),
            ),
            caption="Tablo 1 — Küçük uygunsuzluklar ve sorumlular.",
            widths=(0.5, 0.6, 2.1, 1),
        ),
        P(
            "NC-1: Üç aylık ayrıcalıklı erişim gözden geçirmesi, 2026 birinci çeyreğinde iki "
            "sistem için (faturalama yönetim paneli ve log arşivi) planlanan tarihten sonra, 41 "
            "gün gecikmeyle yapılmıştır. Parola ve Erişim Politikası gözden geçirmenin her "
            "çeyrekte yapılmasını şart koşmaktadır."
        ),
        P(
            "NC-2: Kişisel veri işleyen tedarikçiler listesinde yer alan bir SMS hizmet "
            "sağlayıcısı için yıllık bilgi güvenliği değerlendirme anketi 2026 yılında "
            "doldurtulmamıştır. Satın alma sürecinde anketin sözleşme yenilemesinden önce "
            "tamamlanması gerekmektedir."
        ),
        P(
            "NC-3: 23 Mayıs 2026 tarihli felaket kurtarma testinin sonuç kaydında test "
            "sonuçlarını onaylayan yetkilinin imzası bulunmamaktadır. Test teknik olarak başarılı "
            "olmakla birlikte, Yedekleme ve Felaket Kurtarma Planı test kayıtlarının yetkili "
            "tarafından imzalanmasını gerektirmektedir."
        ),
        H2("4.2 Gözlemler"),
        T(
            ("No", "Konu", "Öneri"),
            (
                ("G-1", "İzmir temiz masa", "Vardiya devrinde kontrol"),
                ("G-2", "Farkındalık eğitimi %94", "Hedef %100"),
                ("G-3", "Log saklama belgesi", "Süreleri tek yerde topla"),
                ("G-4", "Monitör etiketleri", "Envanterle eşleştir"),
            ),
            widths=(0.5, 1.6, 1.6),
        ),
        P(
            "Gözlemler uygunsuzluk niteliği taşımaz; ancak bir sonraki denetimde tekrar edilmeleri "
            "halinde uygunsuzluğa dönüşebilir. G-2 kapsamında bilgi güvenliği farkındalık "
            "eğitimini tamamlama oranı denetim tarihinde %94 olarak ölçülmüştür; eksik kalan "
            "çalışanların büyük kısmı Mart 2026 sonrasında işe başlayan personeldir."
        ),
        H2("4.3 Güçlü Yönler"),
        UL(
            "Nisan 2026'daki veritabanı kesintisi sonrası hazırlanan suçlamasız (blameless) olay "
            "sonrası analiz ve aksiyon takibi örnek uygulama olarak not edilmiştir.",
            "Parola politikasının v2.0 sürümüyle 14 karakter alt sınırı ve FIDO2 anahtar "
            "zorunluluğu getirilmesi olumlu değerlendirilmiştir.",
            "Release kalite kapısının güvenlik taraması kriterleri yazılım geliştirme yaşam "
            "döngüsü kontrollerini güçlü biçimde desteklemektedir.",
        ),
        H1("5. Düzeltici Faaliyet Planı"),
        T(
            ("Bulgu", "Faaliyet", "Termin"),
            (
                ("NC-1", "Otomatik hatırlatma", "31.07.2026"),
                ("NC-2", "Anket tamamlatma", "15.07.2026"),
                ("NC-3", "Kayıt imzası ve şablon", "30.06.2026"),
            ),
            widths=(0.6, 1.8, 1),
        ),
        P(
            "Tüm düzeltici faaliyetlerin kök neden analizleriyle birlikte en geç 9 Eylül 2026 "
            "tarihinde Certa Belgelendirme A.Ş.'ye iletilmesi gerekmektedir. Takip Kalite "
            "Yönetimi tarafından iki haftada bir yapılır; durum Denetim Komitesi Başkanı Dr. "
            "Levent Sarıgül'e aylık olarak raporlanır."
        ),
        H1("6. Sonraki Adımlar"),
        OL(
            "Düzeltici faaliyet kanıtlarının belgelendirme kuruluşuna gönderilmesi (Pınar Yalçın).",
            "FRA-1 ve Berlin ofisini kapsayan kapsam genişletme başvurusu (Aralık 2026).",
            "Yeniden belgelendirme denetimi öncesi iç denetim (Mart 2027).",
            "Yönetimin gözden geçirme toplantısı (Ocak 2027).",
        ),
    ),
)

QUALITY_GATE = Doc(
    path="kalite-yonetimi/Release_Kalite_Kapisi_Proseduru.docx",
    title="Release Kalite Kapısı Prosedürü",
    subtitle="NebulaCRM sürüm adaylarının üretime çıkış kriterleri ve Go/No-Go süreci",
    lang="tr",
    date=D(2026, 1, 12),
    doc_no="KAL-PRO-004",
    meta=(
        ("Sürüm", "3.0"),
        ("Sahibi", "Selin Arslan, Kalite Müdürü"),
        ("Onaylayan", "Ayşe Demir, Ar-Ge Müdürü"),
        ("Yürürlük", "19 Ocak 2026"),
    ),
    blocks=(
        H1("1. Amaç"),
        P(
            "Bu prosedür, NebulaCRM sürüm adaylarının (release candidate) üretime çıkmadan önce "
            "karşılaması gereken asgari kalite kriterlerini ve Go/No-Go kararının nasıl "
            "verileceğini tanımlar. Amaç, müşteriye ulaşan hata sayısını düşürmek ve sürüm "
            "kararlarını kişisel yargıdan çok ölçülebilir kanıta dayandırmaktır."
        ),
        H1("2. Kapsam"),
        P(
            "Prosedür, iki haftada bir salı günü çıkan düzenli sürüm trenlerini ve planlı ara "
            "sürümleri kapsar. Sev-1 veya Sev-2 olaylar için çıkarılan acil düzeltmeler (hotfix) "
            "kısaltılmış kapıya tabidir (bkz. Bölüm 6). Mobil uygulama sürümleri için ayrıca "
            "mağaza onay süreleri dikkate alınır."
        ),
        H1("3. Roller"),
        UL(
            "Kalite Müdürü (Selin Arslan): Go/No-Go toplantısına başkanlık eder ve nihai kararı "
            "kayda geçirir.",
            "Sürüm sorumlusu (Ar-Ge'den dönüşümlü atanır): kalite kapısı raporunu toplantıdan "
            "önce hazırlar.",
            "Test Mühendisi (Hakan Bulut): otomasyon ve performans sonuçlarını doğrular.",
            "Ürün Sahibi (İrem Korkmaz): kapsam ve bilinen hatalar listesini onaylar.",
            "Nöbetçi DevOps mühendisi: dağıtım ve geri alma planını sunar.",
        ),
        H1("4. Kalite Kapısı Kriterleri"),
        P(
            "Bir sürüm adayının Go kararı alabilmesi için aşağıdaki tablodaki tüm kriterleri "
            "karşılaması gerekir. Tek bir kriterin karşılanmaması No-Go anlamına gelir; istisna "
            "yalnızca Bölüm 7'deki muafiyet süreciyle mümkündür."
        ),
        T(
            ("No", "Kriter", "Eşik", "Kanıt kaynağı"),
            (
                ("K1", "Yeni kod birim test kapsamı", "En az %80", "CI kapsam raporu"),
                ("K2", "Toplam kod kapsamı", "En az %70", "CI kapsam raporu"),
                ("K3", "Açık P1/P2 hata", "0 adet", "Hata takip sistemi"),
                ("K4", "Uçtan uca duman testleri", "%100 başarılı", "Staging test raporu"),
                ("K5", "p95 gecikme gerilemesi", "En fazla %10", "Performans karşılaştırması"),
                ("K6", "Güvenlik taraması", "0 kritik / 0 yüksek", "SAST ve bağımlılık taraması"),
                ("K7", "Staging bekleme süresi", "En az 48 saat", "Dağıtım kaydı"),
                ("K8", "Veritabanı göçü", "Geri alınabilir", "Göç inceleme kaydı"),
            ),
        ),
        P(
            "K5 kriterinde karşılaştırma, bir önceki üretim sürümünün staging ortamındaki p95 "
            "değeriyle ve aynı yük profiliyle yapılır. Örneğin önceki sürümde 180 milisaniye "
            "ölçülen bir uç nokta için yeni sürümde kabul edilebilir üst sınır 198 "
            "milisaniyedir."
        ),
        P(
            "K6 kapsamında orta seviyeli güvenlik bulguları sürümü durdurmaz, ancak 30 gün içinde "
            "kapatılmak üzere iş kalemi açılması zorunludur. Düşük seviyeli bulgular üç aylık "
            "güvenlik gözden geçirmesinde ele alınır."
        ),
        H1("5. Go/No-Go Toplantısı"),
        P(
            "Toplantı sürüm günü saat 14:00'te yapılır ve en fazla 30 dakika sürer. Sürüm "
            "sorumlusu kalite kapısı raporunu toplantıdan en az iki saat önce paylaşır. Karar "
            "Kalite Müdürü tarafından toplantı notuna Go, Koşullu Go veya No-Go olarak yazılır. "
            "Koşullu Go kararında koşulların kim tarafından ve hangi saate kadar karşılanacağı "
            "belirtilir; koşul karşılanmazsa sürüm bir sonraki trene kalır."
        ),
        P(
            "Go kararından sonra kademeli dağıtım başlar. Kademeli dağıtımın herhangi bir "
            "aşamasında hata oranı %1'i veya p95 gecikme 250 milisaniyeyi 10 dakikadan uzun süre "
            "aşarsa nöbetçi DevOps mühendisi sürümü onay beklemeden geri alır."
        ),
        H1("6. Acil Düzeltmeler (Hotfix)"),
        P(
            "Hotfix'ler için K1, K3 (yalnızca düzeltilen hatayla ilgili), K4 ve K6 zorunludur; K7 "
            "staging bekleme süresi 2 saate indirilir. Hotfix kararını Kalite Müdürü ve nöbetçi "
            "lider birlikte verir; Kalite Müdürü'ne ulaşılamazsa Kalite Uzmanı Pınar Yalçın "
            "vekâlet eder."
        ),
        H1("7. Muafiyet Süreci"),
        P(
            "Bir kriterin karşılanamadığı ancak sürümün iş açısından kritik olduğu durumlarda "
            "yazılı muafiyet talep edilebilir. Muafiyet, Kalite Müdürü ve Ar-Ge Müdürü'nün "
            "birlikte onayını gerektirir ve gerekçe, risk ve telafi planını içerir. K3 ve K6 "
            "kriterleri için muafiyet verilemez. Bir çeyrekte en fazla 2 muafiyet onaylanabilir; "
            "verilen muafiyetler çeyreklik kalite metrikleri raporunda listelenir."
        ),
        H1("8. Sürüm Dondurma Dönemi"),
        P(
            "Yıl sonu yoğunluğu ve müşterilerin mali kapanış süreçleri nedeniyle her yıl 15 Aralık "
            "ile 5 Ocak arasında sürüm dondurma uygulanır. Bu dönemde yalnızca hotfix çıkarılabilir; "
            "düzenli sürüm trenleri çalışmaz. 2026 yılının son düzenli sürümü olan v3.5'in 8 "
            "Aralık 2026'da çıkması planlanmıştır."
        ),
        H1("9. Kayıtlar"),
        P(
            "Kalite kapısı raporları ve Go/No-Go toplantı notları en az 3 yıl saklanır. Bu kayıtlar "
            "ISO 9001 ve ISO/IEC 27001 denetimlerinde kanıt olarak kullanılır."
        ),
        H1("10. Revizyon Geçmişi"),
        T(
            ("Sürüm", "Tarih", "Açıklama"),
            (
                ("2.0", "06.01.2025", "K5 eşiği %15 olarak tanımlandı"),
                ("2.1", "01.07.2025", "Staging bekleme 24 saat"),
                ("3.0", "12.01.2026", "K5 %10, staging 48 saat, K8 eklendi"),
            ),
        ),
    ),
)

QUALITY_METRICS = Doc(
    path="kalite-yonetimi/Kalite_Metrikleri_2026_Q3.txt",
    title="Kalite Metrikleri Raporu — 2026 3. Çeyrek",
    subtitle="Temmuz–Eylül 2026 yazılım kalitesi ve teslimat göstergeleri",
    lang="tr",
    date=D(2026, 10, 8),
    doc_no="KAL-RAP-2026-Q3",
    meta=(
        ("Hazırlayan", "Pınar Yalçın, Kalite Uzmanı"),
        ("Gözden geçiren", "Selin Arslan, Kalite Müdürü"),
        ("Dönem", "01.07.2026 – 30.09.2026"),
    ),
    blocks=(
        H1("1. Yönetici Özeti"),
        P(
            "Üçüncü çeyrekte müşteriye ulaşan (kaçan) hata sayısı 14'e düştü; ikinci çeyrekte bu "
            "sayı 22 idi. Değişiklik başarısızlık oranı %5,8'den %4,1'e geriledi ve Sev-1/Sev-2 "
            "olaylarda ortalama düzeltme süresi (MTTR) 1 saat 12 dakika oldu. İkinci çeyreğin "
            "MTTR değeri 2 saat 35 dakikaydı; bu değeri 17 Nisan 2026'daki 167 dakikalık "
            "veritabanı kesintisi yukarı çekmişti."
        ),
        P(
            "Çeyrek boyunca 7 sürüm treni çıkarıldı ve v3.4, 15 Eylül 2026'da planlanan tarihte "
            "yayınlandı. Hotfix sayısı 5'ten 2'ye indi. Kalite kapısı için bir muafiyet "
            "onaylandı (v3.4 öncesi, K2 toplam kapsam kriteri; toplam kapsam %69,4 ölçüldü)."
        ),
        H1("2. Göstergeler"),
        T(
            ("Gösterge", "2026 Ç2", "2026 Ç3", "Hedef"),
            (
                ("Kaçan hata sayısı", "22", "14", "≤ 15"),
                ("Değişiklik başarısızlık oranı", "%5,8", "%4,1", "≤ %5"),
                ("Günlük dağıtım sayısı (ort.)", "3,1", "3,6", "≥ 3"),
                (
                    "MTTR (Sev-1/Sev-2)",
                    "2 saat 35 dakika",
                    "1 saat 12 dakika",
                    "≤ 1 saat 30 dakika",
                ),
                ("Otomatik test sayısı", "16.950", "18.420", "-"),
                ("Kararsız (flaky) test oranı", "%2,2", "%1,3", "≤ %1,5"),
                ("Yeni kod kapsamı (ort.)", "%81", "%84", "≥ %80"),
                ("Sürüm treni sayısı", "6", "7", "-"),
                ("Hotfix sayısı", "5", "2", "≤ 3"),
                ("Değişiklik teslim süresi", "3,1 gün", "2,4 gün", "≤ 3 gün"),
            ),
        ),
        H1("3. Kaçan Hataların Dağılımı"),
        P(
            "Q3'teki 14 kaçan hatanın 6'sı raporlama ve dışa aktarma modülünde, 4'ü entegrasyonlar "
            "(e-Fatura ve webhook) tarafında, 3'ü mobil uygulamada ve 1'i yetkilendirme "
            "katmanında görüldü. Yetkilendirme hatası P2 olarak sınıflandırıldı: bir rol "
            "değişikliğinin önbellekte 10 dakika gecikmeyle uygulanmasıydı; başka kiracının "
            "verisine erişim söz konusu olmadı."
        ),
        P(
            "Raporlama modülündeki hata yoğunluğu, Q3 müşteri memnuniyeti anketinde en çok "
            "şikâyet edilen konunun rapor dışa aktarma performansı olmasıyla örtüşmektedir. v3.4 "
            "ile yeniden yazılan dışa aktarma altyapısının etkisi Q4 raporunda ölçülecektir."
        ),
        H2("3.1 Sürüm Trenleri"),
        T(
            ("Tren tarihi", "Sürüm", "Kapı kararı", "Kaçan hata"),
            (
                ("07.07.2026", "v3.3.4", "Go", "2"),
                ("21.07.2026", "v3.3.5", "Go", "3"),
                ("04.08.2026", "v3.3.6", "Koşullu Go", "1"),
                ("18.08.2026", "v3.3.7", "Go", "2"),
                ("01.09.2026", "v3.3.8", "Go", "1"),
                ("15.09.2026", "v3.4.0", "Go (muafiyetli)", "4"),
                ("29.09.2026", "v3.4.1", "Go", "1"),
            ),
        ),
        P(
            "4 Ağustos 2026 treninde verilen Koşullu Go kararının koşulu, e-Fatura entegrasyonundaki "
            "bir P3 hatanın düzeltmesinin aynı gün 18:00'e kadar staging'de doğrulanmasıydı; koşul "
            "17:20'de karşılandı. v3.4.0 sonrasında görülen 4 kaçan hatanın 3'ü yeni dışa aktarma "
            "altyapısıyla ilgiliydi ve v3.4.1 ile giderildi."
        ),
        H1("4. Test Otomasyonu"),
        P(
            "Otomatik test sayısı çeyrek içinde 1.470 artarak 18.420'ye ulaştı. Bunların yaklaşık "
            "%71'i birim, %22'si entegrasyon ve %7'si uçtan uca testtir. Kararsız test oranı, "
            "Temmuz'da başlatılan karantina uygulamasıyla %1,3'e indi: art arda üç koşuda farklı "
            "sonuç veren test otomatik olarak karantinaya alınıyor ve sahibine 5 iş günü süre "
            "veriliyor. Uçtan uca test paketinin süresi 41 dakikadan 27 dakikaya kısaldı."
        ),
        H1("5. Olaylar"),
        P(
            "Q3'te Sev-1 olay yaşanmadı. 3 adet Sev-2 olay kaydedildi; en uzunu 19 Ağustos "
            "2026'da e-posta bildirim kuyruğunda 48 dakikalık gecikmeydi. Tüm Sev-2 olaylar için "
            "olay sonrası analiz 5 iş günü içinde tamamlandı."
        ),
        H1("6. Q4 2026 Öncelikleri"),
        UL(
            "Toplam kod kapsamını %70'in üzerine kalıcı olarak çıkarmak (v3.4'te muafiyet "
            "gerekti).",
            "Hotfix sayısını çeyrekte en fazla 3'te tutmak.",
            "Yük testini Nebula Assist trafiğini de içerecek şekilde v3.4 üzerinde tekrarlamak.",
            "ISO/IEC 27001 kapsam genişletme başvurusu için FRA-1 kontrol kanıtlarını hazırlamak.",
            "15 Aralık – 5 Ocak sürüm dondurma dönemi öncesinde v3.5'i 8 Aralık 2026'da çıkarmak.",
        ),
        H1("7. Tanımlar"),
        UL(
            "Kaçan hata: üretimde müşteri veya izleme tarafından tespit edilen, sürüm öncesi "
            "testlerde yakalanmamış hata.",
            "Değişiklik başarısızlık oranı: geri alma, hotfix veya olayla sonuçlanan üretim "
            "dağıtımlarının toplam dağıtımlara oranı.",
            "MTTR: Sev-1 ve Sev-2 olaylarda olayın başlangıcından hizmetin normale dönmesine "
            "kadar geçen ortalama süre.",
            "Değişiklik teslim süresi: birleştirmeden üretime çıkışa kadar geçen medyan süre.",
        ),
    ),
)

DOCS = [ISO_AUDIT, QUALITY_GATE, QUALITY_METRICS]
