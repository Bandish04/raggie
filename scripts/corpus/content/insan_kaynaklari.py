# SPDX-License-Identifier: Apache-2.0

"""İnsan Kaynakları: remote/hybrid policy, leave regulation, performance & bonus, hiring guide."""

from model import H1, H2, OL, UL, D, Doc, P, T

REMOTE = Doc(
    path="insan-kaynaklari/Uzaktan_ve_Hibrit_Calisma_Politikasi_2026.docx",
    title="Uzaktan ve Hibrit Çalışma Politikası",
    lang="tr",
    date=D(2026, 2, 20),
    doc_no="IK-POL-012",
    meta=(
        ("Sürüm", "3.0"),
        ("Sahibi", "Burak Çelik, İnsan Kaynakları Müdürü"),
        ("Onaylayan", "Mehmet Yılmaz, CEO"),
        ("Yürürlük", "1 Mart 2026"),
    ),
    blocks=(
        H1("1. Amaç"),
        P(
            "Bu politika, Nebula Teknoloji A.Ş.'de hibrit ve uzaktan çalışmanın hangi koşullarda "
            "uygulanacağını, çalışanların ve yöneticilerin sorumluluklarını ve uzaktan çalışmaya bağlı "
            "destekleri tanımlar. Amacımız, ekiplerin birlikte üretme ihtiyacını korurken çalışanlara "
            "öngörülebilir bir esneklik sağlamaktır."
        ),
        H1("2. Kapsam"),
        P(
            "Politika, İstanbul Genel Merkez ve Ankara Ar-Ge Ofisi'nde belirsiz süreli iş sözleşmesiyle "
            "çalışan tüm personeli kapsar. İzmir Müşteri Destek Merkezi'nde vardiya düzeninde çalışan "
            "personel bu politikanın kapsamı dışındadır; vardiya çalışanlarının çalışma düzeni İzmir "
            "vardiya yönergesinde belirlenir. Berlin ofisi çalışanları Nebula Technology GmbH'nin yerel "
            "çalışma düzenine tabidir."
        ),
        H1("3. Tanımlar"),
        UL(
            "Hibrit çalışma: Çalışanın haftanın bir bölümünü ofiste, kalan bölümünü uzaktan geçirdiği varsayılan çalışma modeli.",
            "Tam uzaktan çalışma: Çalışanın ofise düzenli olarak gelmeden çalıştığı, onaya bağlı istisnai model.",
            "Çekirdek ofis günleri: Hibrit çalışanların ofiste bulunmasının beklendiği günler; 2026 itibarıyla Salı ve Perşembe.",
            "Çekirdek saatler: Konumdan bağımsız olarak tüm çalışanların çevrim içi ve ulaşılabilir olduğu 10:00–16:00 aralığı.",
        ),
        H1("4. Çalışma modelleri"),
        H2("4.1 Hibrit çalışma (varsayılan model)"),
        P(
            "Hibrit çalışanlar haftada en az 2 gün ofiste bulunur. Bu günlerden ikisi çekirdek ofis günleri "
            "olan Salı ve Perşembe'dir. Ekipler, sprint planlaması veya müşteri ziyaretleri gibi "
            "ihtiyaçlar doğrultusunda ek ofis günleri belirleyebilir; ancak bu günler en az bir hafta "
            "önceden duyurulur."
        ),
        H2("4.2 Tam uzaktan çalışma"),
        P(
            "Tam uzaktan çalışma; departman yöneticisinin önerisi ve İnsan Kaynakları Müdürü'nün onayıyla "
            "uygulanır. Talep; görevin niteliği, çalışanın performans geçmişi ve ekip ihtiyacı birlikte "
            "değerlendirilerek karara bağlanır. Tam uzaktan çalışma onayları 6 ayda bir gözden geçirilir. "
            "Tam uzaktan çalışanlar çeyrekte en az bir kez, masrafları şirket tarafından karşılanarak, "
            "bağlı oldukları ofiste ekip buluşmasına katılır."
        ),
        H2("4.3 Geçici düzenlemeler"),
        P(
            "Sağlık, bakım yükümlülüğü veya taşınma gibi geçici durumlarda çalışan, yöneticisinin onayıyla "
            "en fazla 8 haftalık geçici tam uzaktan çalışma düzenlemesinden yararlanabilir. Bu süre "
            "İnsan Kaynakları onayıyla bir kez uzatılabilir."
        ),
        H1("5. Çalışma saatleri ve ulaşılabilirlik"),
        P(
            "Haftalık çalışma süresi 45 saattir. Çalışanlar mesailerini 08:00–19:00 aralığında esnek "
            "olarak planlayabilir; ancak 10:00–16:00 çekirdek saatlerinde toplantılara katılabilir ve "
            "mesajlara makul sürede yanıt verebilir durumda olmalıdır. Uzaktan çalışılan günlerde "
            "kurumsal takvimde konum bilgisi güncel tutulur. Mesai dışı iletişimde acil durumlar "
            "dışında yanıt beklenmez."
        ),
        H1("6. Ödenekler ve destekler"),
        P(
            "Uzaktan çalışma ödeneğine hak kazanmak için çalışanın bir takvim ayı içinde ortalama olarak "
            "haftada en az 2 gün uzaktan çalışmış olması gerekir. Uygunluk, ofis giriş kartı kayıtları "
            "esas alınarak her ay İK tarafından hesaplanır ve ödenek takip eden ayın bordrosuyla ödenir. "
            "Yıllık izin ve raporlu günler hesaplamada uzaktan çalışma günü sayılmaz."
        ),
        P(
            "Uzaktan çalışma ödeneği ile ev-ofis kurulum desteğinin tutarları bu politikada yer almaz. "
            "Tutarlar her yıl Finans Müdürlüğü'nün hazırladığı ve Yönetim Kurulu'nun onayladığı yıllık "
            "bütçede belirlenir. 2026 yılı tutarları için '2026 Bütçe ve Gider Planı' dosyasının "
            "'Yan Haklar ve Ödenekler' sayfasına bakınız."
        ),
        P(
            "Ev-ofis kurulum desteği, hibrit veya uzaktan modele ilk kez geçen çalışana bir defaya mahsus "
            "ödenir ve çalışma masası, ergonomik sandalye ya da aydınlatma gibi kalemler için kullanılır. "
            "Desteğin ödenmesi için harcama belgelerinin geçiş tarihinden itibaren 60 gün içinde İK "
            "Portalı'na yüklenmesi gerekir. Destek, aynı çalışana 3 yıl geçmeden yeniden ödenmez."
        ),
        H1("7. Ekipman"),
        UL(
            "Dizüstü bilgisayar, ek monitör, klavye ve kulaklık BT Müdürlüğü tarafından zimmetle teslim edilir.",
            "Şirket ekipmanı yalnızca çalışan tarafından ve iş amacıyla kullanılır; aile bireylerinin kullanımına açılmaz.",
            "Arızalı veya kaybolan ekipman 24 saat içinde BT yardım masasına bildirilir.",
            "İş ilişkisinin sona ermesi hâlinde tüm ekipman son çalışma gününde iade edilir.",
        ),
        H1("8. Bilgi güvenliği"),
        P(
            "Uzaktan çalışırken şirket sistemlerine yalnızca şirket VPN'i üzerinden ve çok faktörlü "
            "kimlik doğrulama ile erişilir. Halka açık kablosuz ağlarda VPN bağlanmadan çalışılmaz. "
            "Ekran kilidi en fazla 5 dakika hareketsizlikten sonra devreye girecek şekilde ayarlanır. "
            "Müşteri verisi içeren belgeler basılı olarak evde saklanmaz. Parola ve erişim kuralları "
            "için BT-POL-002 Parola ve Erişim Politikası esas alınır."
        ),
        H1("9. Yurt dışından çalışma"),
        P(
            "Çalışanlar takvim yılı içinde toplam en fazla 20 iş günü yurt dışından çalışabilir. Talep, "
            "seyahatten en az 15 gün önce İK Portalı üzerinden yapılır ve yöneticinin yanında İnsan "
            "Kaynakları'nın onayını gerektirir. Hukuk ve Uyum Müdürlüğü'nün yaptırım ve veri aktarımı "
            "değerlendirmesi nedeniyle kısıtlı ülkeler listesindeki ülkelerden çalışmaya izin verilmez. "
            "Yurt dışından çalışılan günler için uzaktan çalışma ödeneğine ek bir ödeme yapılmaz."
        ),
        H1("10. İş sağlığı ve güvenliği"),
        P(
            "Uzaktan çalışma ortamının ergonomik ve güvenli olmasından çalışan sorumludur. İK, her yıl "
            "Nisan ayında uzaktan çalışma ortamı öz değerlendirme formu gönderir; form 30 gün içinde "
            "doldurulur. Uzaktan çalışılan günlerde yaşanan iş kazaları aynı gün yöneticiye ve İK'ya "
            "bildirilir."
        ),
        H1("11. Politikaya aykırılık"),
        P(
            "Çekirdek ofis günlerine ardışık olarak uyulmaması önce yöneticiyle birebir görüşmeyle ele "
            "alınır. Uyumsuzluğun üç ay içinde tekrar etmesi hâlinde çalışan, İK onayıyla hibrit "
            "modelden ofis temelli modele alınabilir ve bu durumda uzaktan çalışma ödeneği kesilir."
        ),
        H1("12. Değişiklik geçmişi"),
        T(
            ("Sürüm", "Yürürlük", "Özet"),
            (
                ("1.0", "01.04.2021", "İlk yayın; haftada 1 gün ofis"),
                (
                    "2.0",
                    "02.01.2024",
                    "Haftada 3 gün ofis; çekirdek günler Salı, Çarşamba, Perşembe",
                ),
                ("3.0", "01.03.2026", "Haftada en az 2 gün ofis; çekirdek günler Salı ve Perşembe"),
            ),
        ),
    ),
)

LEAVE = Doc(
    path="insan-kaynaklari/Izin_Yonetmeligi_2026.pdf",
    title="İzin Yönetmeliği",
    subtitle="Yıllık ücretli izin, mazeret izinleri ve izin süreçleri",
    lang="tr",
    date=D(2026, 1, 2),
    doc_no="IK-YON-003",
    meta=(
        ("Sürüm", "5.0"),
        ("Sahibi", "Burak Çelik, İnsan Kaynakları Müdürü"),
        ("Onaylayan", "Mehmet Yılmaz, CEO"),
        ("Yürürlük", "1 Ocak 2026"),
    ),
    blocks=(
        H1("1. Amaç ve dayanak"),
        P(
            "Bu yönetmelik, 4857 sayılı İş Kanunu ve ilgili mevzuat çerçevesinde Nebula Teknoloji A.Ş. "
            "çalışanlarının izin haklarını ve izin kullanım süreçlerini düzenler. Yönetmelikte yer alan "
            "şirket ek hakları yasal asgari hakların üzerine eklenir; hiçbir hüküm yasal hakları "
            "daraltacak şekilde yorumlanamaz."
        ),
        H1("2. Kapsam"),
        P(
            "Yönetmelik İstanbul, Ankara ve İzmir ofislerindeki tüm çalışanları kapsar. Berlin ofisi "
            "çalışanları Nebula Technology GmbH iş sözleşmelerindeki 28 iş günlük yıllık izin hakkına "
            "tabidir."
        ),
        H1("3. Yıllık ücretli izin"),
        P(
            "Yıllık izin süresi çalışanın kıdemine göre belirlenir. Şirket, yasal sürenin üzerine her "
            "kıdem grubunda 2 iş günü Nebula ek izni tanır. 2025 yılında 1 iş günü olan Nebula ek izni, "
            "1 Ocak 2026'dan itibaren 2 iş gününe çıkarılmıştır."
        ),
        T(
            ("Kıdem", "Yasal izin", "Nebula ek izni", "Toplam"),
            (
                ("1 yıl – 5 yıl (5 dahil)", "14 iş günü", "2 iş günü", "16 iş günü"),
                ("5 yıl – 15 yıl", "20 iş günü", "2 iş günü", "22 iş günü"),
                ("15 yıl ve üzeri", "26 iş günü", "2 iş günü", "28 iş günü"),
            ),
            widths=(2.0, 1.2, 1.3, 1.2),
        ),
        P(
            "18 yaşından küçük ve 50 yaşından büyük çalışanların yıllık izin süresi kıdemlerinden "
            "bağımsız olarak 20 iş gününden az olamaz. Deneme süresi içindeki çalışanlar, ilk yıllarını "
            "doldurmadan önce yöneticinin onayıyla en fazla 5 iş günü avans izin kullanabilir."
        ),
        H1("4. Mazeret ve özel izinler"),
        P(
            "Aşağıdaki izinler ücretli olup yıllık izinden düşülmez. Şirket uygulaması, yasal sürenin "
            "üzerinde olduğu hâllerde şirket süresi esas alınır."
        ),
        T(
            ("İzin türü", "Yasal süre", "Nebula uygulaması"),
            (
                ("Evlilik izni", "3 gün", "5 iş günü"),
                ("Babalık izni", "5 gün", "10 iş günü"),
                ("Vefat (birinci derece)", "3 gün", "5 iş günü"),
                ("Taşınma izni", "—", "1 iş günü / yıl"),
                ("Doğum günü izni", "—", "1 iş günü"),
                ("Gönüllülük izni", "—", "1 iş günü / yıl"),
            ),
            widths=(2.0, 1.2, 1.6),
        ),
        P(
            "Doğum günü izni, çalışanın doğum gününün bulunduğu ay içinde kullanılır; kullanılmayan "
            "doğum günü izni sonraki aya veya yıla devretmez. Gönüllülük izni, şirketin anlaşmalı olduğu "
            "sivil toplum kuruluşlarının etkinliklerinde kullanılabilir. Annelik izni ve süt izni "
            "yasal süreler çerçevesinde uygulanır."
        ),
        H1("5. İzin talebi ve onay"),
        UL(
            "Tüm izin talepleri İK Portalı üzerinden yapılır; e-posta ile yapılan talepler geçerli sayılmaz.",
            "3 iş günü ve daha uzun izinler en az 10 iş günü önceden talep edilir.",
            "Yönetici, talebi en geç 3 iş günü içinde onaylar veya gerekçesiyle reddeder.",
            "Yarım gün izin kullanılabilir; yarım günler 09:00–13:00 veya 14:00–18:00 aralıklarıdır.",
            "Aynı ekipte aynı anda izinde olan çalışan sayısı ekibin üçte birini geçmeyecek şekilde planlanır.",
        ),
        H1("6. İzin devri"),
        P(
            "Kullanılmayan yıllık izinlerin en fazla 10 iş günü bir sonraki yıla devredilebilir. Devreden "
            "izinlerin 31 Mart'a kadar kullanılması esastır. Bu tarihe kadar kullanılmayan devreden "
            "izinler, yönetici ve İK tarafından birlikte planlanarak Nisan–Haziran döneminde "
            "kullandırılır. Yıllık izinler ücrete dönüştürülemez; iş sözleşmesinin sona ermesi hâlinde "
            "kullanılmamış izin ücretleri yasal düzenlemeye göre ödenir."
        ),
        H1("7. Hastalık izni"),
        P(
            "Hekim raporu alan çalışan, raporu en geç 2 iş günü içinde İK Portalı'na yükler. Yılda toplam "
            "3 günü aşmayan raporsuz hastalık hâllerinde yöneticinin onayı yeterlidir. Uzun süreli "
            "raporlarda çalışanın işe dönüşünde İK ile kısa bir görüşme yapılır."
        ),
        H1("8. Ücretsiz izin"),
        P(
            "Çalışan, yöneticisinin ve İnsan Kaynakları Müdürü'nün onayıyla en fazla 3 ay ücretsiz izin "
            "kullanabilir. Ücretsiz izin süresince özel sağlık sigortası şirket tarafından karşılanmaya "
            "devam eder; yemek kartı ve uzaktan çalışma ödeneği ödenmez."
        ),
        H1("9. Resmî tatiller ve köprü günleri"),
        P(
            "Ulusal bayram ve genel tatillerde ofisler kapalıdır. Yönetim, köprü günlerini her yıl Aralık "
            "ayında bir sonraki yıl için ilan eder; köprü günleri yıllık izinden düşülür. İzmir Müşteri "
            "Destek Merkezi'nde resmî tatillerde çalışan vardiya personeline yasal fazla çalışma ücreti "
            "ödenir."
        ),
        H1("10. İzin bakiyesi ve raporlama"),
        P(
            "Çalışanlar güncel izin bakiyelerini İK Portalı'ndaki 'İzinlerim' ekranından izleyebilir. "
            "İK, her yıl Ekim ayında bakiyesi 15 iş gününün üzerinde olan çalışanların listesini "
            "yöneticilerle paylaşır ve yıl sonuna kadar izin planı yapılmasını ister. Yöneticiler, "
            "ekiplerinin izin planlarını Aralık ayının ilk haftasına kadar portala girer."
        ),
        P(
            "Bu yönetmelikle ilgili sorular için İK Uzmanı Sıla Çetin'e veya ik@nebulacrm.example "
            "adresine başvurulabilir."
        ),
    ),
)

PERFORMANCE = Doc(
    path="insan-kaynaklari/Performans_Degerlendirme_ve_Prim_Sistemi.pdf",
    title="Performans Değerlendirme ve Prim Sistemi",
    lang="tr",
    date=D(2026, 1, 15),
    doc_no="IK-POL-020",
    meta=(
        ("Sürüm", "2.1"),
        ("Sahibi", "Burak Çelik, İnsan Kaynakları Müdürü"),
        ("Onaylayan", "Mehmet Yılmaz, CEO"),
        ("Yürürlük", "1 Ocak 2026"),
    ),
    blocks=(
        H1("1. Amaç"),
        P(
            "Bu politika, çalışanların yıllık hedeflerinin belirlenmesini, performanslarının adil ve "
            "tutarlı biçimde değerlendirilmesini ve değerlendirme sonucunun yıllık prime nasıl "
            "yansıdığını tanımlar. Satış ekiplerinin komisyon planları bu politikanın kapsamı dışındadır "
            "ve ayrı bir prim yönergesiyle düzenlenir."
        ),
        H1("2. Değerlendirme döngüleri"),
        UL(
            "Hedef belirleme: Her yıl Ocak ayı sonuna kadar; hedefler İK Portalı'na girilir ve yönetici tarafından onaylanır.",
            "Ara değerlendirme: Temmuz ayında yapılır; puan verilmez, gelişim geri bildirimi ve hedef güncellemesi yapılır.",
            "Yıl sonu değerlendirmesi: Ocak ayında yapılır ve prime esas performans notunu belirler.",
            "Kalibrasyon: Şubat ayının ilk haftasında departman bazında kalibrasyon komiteleri toplanır.",
            "Prim ödemesi: Yıllık prim Mart ayı bordrosuyla ödenir.",
        ),
        P(
            "Değerlendirmede bireysel hedefler %70, Nebula yetkinlikleri (müşteri odaklılık, sahiplenme, "
            "birlikte üretme, öğrenme) %30 ağırlıkla dikkate alınır."
        ),
        H1("3. Performans notları ve prim çarpanları"),
        T(
            ("Not", "Tanım", "Prim çarpanı", "Hedef dağılım"),
            (
                ("5", "Olağanüstü", "%150", "%10"),
                ("4", "Beklentinin üzerinde", "%120", "%25"),
                ("3", "Beklentiyi karşılıyor", "%100", "%50"),
                ("2", "Gelişim gerekli", "%50", "%12"),
                ("1", "Beklentinin altında", "%0", "%3"),
            ),
            widths=(0.6, 2.2, 1.2, 1.2),
        ),
        P(
            "Hedef dağılım bağlayıcı bir kota değildir; kalibrasyon komitesi, dağılımın belirgin şekilde "
            "sapması hâlinde gerekçe ister. 50 kişiden küçük departmanlar dağılım kontrolüne tabi değildir."
        ),
        H1("4. Hedef prim oranları"),
        P("Hedef prim, yıllık brüt temel ücretin yüzdesi olarak kademe bazında belirlenir."),
        T(
            ("Kademe", "Örnek unvanlar", "Hedef prim"),
            (
                ("L1–L2", "Uzman yardımcısı, uzman", "%8"),
                ("L3–L4", "Kıdemli uzman, mühendis", "%12"),
                ("L5", "Yönetici", "%18"),
                ("Direktör", "Departman yöneticileri", "%25"),
            ),
            widths=(1.0, 2.4, 1.0),
        ),
        H1("5. Prim hesaplama"),
        P(
            "Yıllık prim şu formülle hesaplanır: Prim = Yıllık brüt temel ücret × Hedef prim oranı × "
            "Bireysel prim çarpanı × Şirket performans faktörü."
        ),
        P(
            "Şirket performans faktörü, yıllık gelir ve FAVÖK gerçekleşmesine göre Yönetim Kurulu "
            "tarafından belirlenir ve 0 ile 1,3 arasında değer alır. Yıllık gelir bütçenin %85'inin "
            "altında kalırsa faktör 0 olarak uygulanır. 2025 performans yılı için şirket performans "
            "faktörü 0,92 olarak belirlenmiş ve primler Mart 2026 bordrosuyla ödenmiştir."
        ),
        P(
            "Örnek: Yıllık brüt temel ücreti 1.200.000 TL olan, L3 kademesinde ve 4 notu alan bir çalışanın "
            "2025 primi 1.200.000 × %12 × 1,20 × 0,92 = 158.976 TL olarak hesaplanmıştır."
        ),
        H1("6. Prime hak kazanma"),
        UL(
            "Değerlendirme yılının 1 Ekim tarihinden önce işe başlamış olmak gerekir; yıl içinde işe başlayanlara kıst prim ödenir.",
            "Prim ödeme tarihinde iş sözleşmesi devam ediyor olmalıdır; istifa bildiriminde bulunan çalışanlara prim ödenmez.",
            "Uzun süreli ücretsiz izinde geçen süreler prim hesabından düşülür.",
        ),
        H1("7. Gelişim planı ve terfi"),
        P(
            "Yıl sonu değerlendirmesinde 1 veya üst üste iki döngüde 2 notu alan çalışan için yöneticisi ve "
            "İK ile birlikte 60 günlük performans gelişim planı (PGP) hazırlanır. PGP süresince iki "
            "haftada bir ilerleme görüşmesi yapılır."
        ),
        P(
            "Terfi değerlendirmesine alınmak için art arda iki yıl sonu döngüsünde en az 4 notu almak ve "
            "mevcut kademede en az 12 ay çalışmış olmak gerekir. Terfiler Nisan ayında yürürlüğe girer."
        ),
        H1("8. 2026 takvimi"),
        T(
            ("Adım", "Tarih"),
            (
                ("2026 hedeflerinin girişi", "30 Ocak 2026"),
                ("2025 kalibrasyon komiteleri", "2–6 Şubat 2026"),
                ("2025 primlerinin ödenmesi", "Mart 2026 bordrosu"),
                ("Ara değerlendirme dönemi", "6–24 Temmuz 2026"),
                ("Yıl sonu öz değerlendirme", "4–15 Ocak 2027"),
            ),
            widths=(2.6, 1.6),
        ),
        P(
            "Takvim, departman yöneticilerine her yıl Ocak ayının ilk haftasında İK tarafından e-posta ile "
            "duyurulur. Ara değerlendirmeyi süresi içinde tamamlamayan yöneticilerin listesi CEO Ofisi ile "
            "paylaşılır."
        ),
        H1("9. İtiraz"),
        P(
            "Çalışan, değerlendirme sonucunun kendisine bildirilmesinden itibaren 10 iş günü içinde İK "
            "Portalı üzerinden itiraz edebilir. İtirazlar İnsan Kaynakları Müdürü Burak Çelik ve ilgili "
            "departman yöneticisinin üst yöneticisinden oluşan bir heyet tarafından 15 iş günü içinde "
            "sonuçlandırılır."
        ),
    ),
)

HIRING = Doc(
    path="insan-kaynaklari/Ise_Alim_ve_Oryantasyon_Rehberi.md",
    title="İşe Alım ve Oryantasyon Rehberi",
    lang="tr",
    date=D(2026, 4, 1),
    doc_no="IK-REH-004",
    meta=(
        ("Sürüm", "2.0"),
        ("Sahibi", "Berk Güneş, İşe Alım Uzmanı"),
        ("Onaylayan", "Burak Çelik, İnsan Kaynakları Müdürü"),
    ),
    blocks=(
        H1("1. Bu rehber kimin için?"),
        P(
            "Bu rehber, Nebula'da açık pozisyonu olan yöneticiler, mülakatlara katılan çalışanlar ve "
            "yeni başlayan arkadaşlarımızı karşılayan ekipler için hazırlandı. Amaç, her adayın aynı "
            "adil süreçten geçmesini ve her yeni çalışanın ilk gününden itibaren verimli olabilmesini "
            "sağlamaktır."
        ),
        H1("2. İşe alım süreci"),
        OL(
            "Kadro talebi: Yönetici, onaylı yıllık bütçedeki kadro planına dayanarak İK Portalı'ndan talep açar. Bütçede yer almayan ek kadrolar CEO onayı gerektirir.",
            "İlan: Pozisyon önce 5 iş günü boyunca yalnızca şirket içinde duyurulur, ardından dış kanallarda yayımlanır.",
            "Ön eleme: İşe alım ekibi adayla yaklaşık 30 dakikalık bir telefon görüşmesi yapar.",
            "Teknik değerlendirme: Mühendislik rollerinde aday, 72 saat içinde teslim edilecek bir ev ödevi ile 90 dakikalık canlı kodlama oturumu arasında tercih yapar. Diğer rollerde vaka çalışması uygulanır.",
            "Panel mülakat: Biri farklı departmandan olmak üzere 3 kişilik panel, yapılandırılmış sorularla görüşme yapar.",
            "Referans kontrolü: En az 2 referansla görüşülür; mevcut işverenle görüşme yalnızca adayın yazılı izniyle yapılır.",
            "Teklif: Teklif mektubu İK tarafından hazırlanır ve 5 iş günü geçerlidir.",
        ),
        P(
            "Talebin açılmasından teklifin kabulüne kadar geçen süre (time-to-hire) için 2026 hedefimiz "
            "35 gündür. Bu süre 2025 yılında ortalama 41 gün olarak gerçekleşti. Adaylara her aşamanın "
            "ardından en geç 5 iş günü içinde geri bildirim verilir."
        ),
        H1("3. Mülakatçı kuralları"),
        UL(
            "Her mülakatçı, değerlendirme formunu görüşmeden sonraki 24 saat içinde doldurur.",
            "Medeni durum, çocuk sahibi olma planı, dini inanç veya siyasi görüş gibi konularda soru sorulmaz.",
            "Panel üyeleri değerlendirme formlarını birbirlerinin notlarını görmeden doldurur; ortak karar toplantısı formlar tamamlandıktan sonra yapılır.",
            "Yeni mülakatçılar, ilk panel görüşmelerinden önce İK'nın 2 saatlik yapılandırılmış mülakat eğitimini tamamlar.",
        ),
        H1("4. Çalışan referans programı"),
        P(
            "Önerdiğiniz aday işe alınır ve deneme süresini tamamlarsa referans primi ödenir. Deneme süresi "
            "2 aydır ve prim, deneme süresinin bitimini izleyen ilk bordroyla ödenir."
        ),
        T(
            ("Pozisyon grubu", "Referans primi"),
            (
                ("Mühendislik rolleri (Ar-Ge, BT, Kalite)", "40.000 TL"),
                ("Diğer tüm roller", "20.000 TL"),
            ),
        ),
        P(
            "Yöneticiler kendi ekiplerine yapılan işe alımlar için ve İK ekibi üyeleri hiçbir işe alım için "
            "referans primi alamaz. Aynı aday için birden fazla referans yapılmışsa, adayı sisteme ilk "
            "kaydeden çalışan prime hak kazanır."
        ),
        H1("5. Aday verileri ve KVKK"),
        P(
            "Adayların özgeçmişleri ve mülakat notları, başvuru tarihinden itibaren 1 yıl saklanır ve "
            "ardından imha edilir. Adayın açık rızasıyla bu süre 2 yıla uzatılabilir. Aday verileri "
            "yalnızca İK Portalı'nda tutulur; e-posta eklerinin kişisel klasörlerde saklanması yasaktır. "
            "Ayrıntılar için KVKK Kişisel Veri Saklama ve İmha Politikası'na bakınız."
        ),
        H1("6. İlk güne hazırlık"),
        UL(
            "İK, teklif kabul edildiği gün BT'ye ekipman talebi açar; talep en geç başlangıç tarihinden 7 iş günü önce açılmış olmalıdır.",
            "Dizüstü bilgisayar, erişim kartı ve kurumsal hesaplar ilk gün sabah teslim edilir.",
            "Yönetici, yeni çalışana ekibinden bir oryantasyon arkadaşı (buddy) atar ve ilk hafta takvimini hazırlar.",
        ),
        H1("7. Oryantasyon programı"),
        P(
            "'Nebula'ya Hoş Geldin' oryantasyonu her pazartesi saat 10:00'da İstanbul Genel Merkez'de 11. "
            "kattaki Boğaz toplantı salonunda başlar; Ankara ve İzmir'deki yeni çalışanlar oturuma "
            "çevrim içi katılır. Program yarım gün sürer ve CEO Mehmet Yılmaz'ın şirket tarihçesi ve "
            "stratejisi sunumuyla açılır."
        ),
        P(
            "İlk 30 gün içinde tamamlanması zorunlu eğitimler: KVKK farkındalık eğitimi, bilgi güvenliği "
            "eğitimi ve etik kurallar eğitimi. Mühendislik rollerinde ayrıca kod inceleme ve sürüm "
            "süreçleri eğitimi ilk 2 hafta içinde tamamlanır."
        ),
        H1("8. 30-60-90 gün planı"),
        T(
            ("Dönem", "Beklenti", "Kontrol noktası"),
            (
                (
                    "İlk 30 gün",
                    "Ürünü, ekibi ve süreçleri tanıma; zorunlu eğitimler",
                    "Yöneticiyle 30. gün görüşmesi",
                ),
                (
                    "31–60. gün",
                    "İlk bağımsız görevler; deneme süresi sonu",
                    "Deneme süresi değerlendirme formu",
                ),
                (
                    "61–90. gün",
                    "Tam sorumluluk; ilk yıl hedeflerinin belirlenmesi",
                    "İK ile 90. gün geri bildirim anketi",
                ),
            ),
        ),
        H1("9. İletişim"),
        P(
            "Sorularınız için ise-alim@nebulacrm.example adresine yazabilir veya İşe Alım Uzmanı Berk Güneş "
            "ile görüşebilirsiniz."
        ),
    ),
)

DOCS = [REMOTE, LEAVE, PERFORMANCE, HIRING]
