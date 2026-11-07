# SPDX-License-Identifier: Apache-2.0

"""Bilgi Teknolojileri (IT) department documents."""

from model import H1, H2, OL, UL, D, Doc, P, Sheet, T

PASSWORD_V2 = Doc(
    path="bilgi-teknolojileri/Parola_ve_Erisim_Politikasi_v2.0_2026.pdf",
    title="Parola ve Erişim Yönetimi Politikası",
    subtitle="Sürüm 2.0 — v1.3 (2025) sürümünün yerini alır",
    lang="tr",
    date=D(2026, 2, 16),
    doc_no="BT-POL-002",
    meta=(
        ("Sürüm", "2.0"),
        ("Sahibi", "Emre Kaya, BT Müdürü"),
        ("Hazırlayan", "Murat Şen, Sistem Yöneticisi"),
        ("Onaylayan", "Mehmet Yılmaz, CEO"),
        ("Yürürlük", "1 Mart 2026"),
    ),
    blocks=(
        H1("1. Amaç"),
        P(
            "Bu politika, Nebula Teknoloji A.Ş. bünyesindeki tüm kurumsal sistemlere, NebulaCRM üretim "
            "ortamına ve müşteri verisine erişimde kullanılan kimlik doğrulama yöntemlerini ve erişim "
            "yetkilerinin yaşam döngüsünü tanımlar. Politika, ISO/IEC 27001:2022 Ek A kontrolleri 5.15–5.18 "
            "ve 8.5 ile uyumlu olacak şekilde hazırlanmıştır."
        ),
        P(
            "Sürüm 2.0, 15 Ocak 2025'te yürürlüğe giren v1.3 sürümünün yerini alır. Güncellemenin temel "
            "gerekçesi, zorunlu periyodik parola değişiminin kullanıcıları tahmin edilebilir parolalara "
            "yönelttiğinin iç denetimde tespit edilmesi ve çok faktörlü kimlik doğrulamanın (MFA) yalnızca "
            "VPN ve e-posta ile sınırlı kalmasının kabul edilemez bir risk olarak değerlendirilmesidir."
        ),
        H1("2. Kapsam"),
        P(
            "Politika; tüm çalışanları, stajyerleri, Nebula Technology GmbH personelini, yükleniciler ile "
            "danışmanları ve şirket adına sistemlere erişen tüm üçüncü tarafları kapsar. İstanbul, Ankara, "
            "İzmir ve Berlin ofislerinde ayrım yapılmaksızın uygulanır. Müşterilerin NebulaCRM içindeki son "
            "kullanıcı hesapları bu politikanın kapsamı dışındadır; bu hesaplar için ürün içi parola kuralları "
            "müşteri yöneticileri tarafından yapılandırılır."
        ),
        H1("3. Parola Kuralları"),
        UL(
            "Kullanıcı parolaları en az 14 karakter uzunluğunda olmalıdır. Karakter türü zorunluluğu "
            "aranmaz; dört veya daha fazla rastgele kelimeden oluşan parola cümleleri önerilir.",
            "Parolalar periyodik olarak değiştirilmez. Parola yalnızca ele geçirildiğinden şüphelenildiğinde, "
            "bir güvenlik olayı sonrasında veya BT ekibinin talebiyle değiştirilir.",
            "Yeni parola, sızdırılmış parola listesine karşı otomatik olarak kontrol edilir; listede yer alan "
            "parolalar kabul edilmez.",
            "Parola geçmişi son 12 parolayı tutar; bu parolalar yeniden kullanılamaz.",
            "Art arda 10 hatalı giriş denemesinden sonra hesap 15 dakika süreyle kilitlenir.",
            "Tüm çalışanlar kurumsal parola kasasını kullanmak zorundadır; parolaların tarayıcıda, not "
            "dosyalarında veya kağıt üzerinde saklanması yasaktır.",
            "Ekran kilidi, 10 dakika hareketsizlikten sonra otomatik olarak devreye girer.",
        ),
        H1("4. Çok Faktörlü Kimlik Doğrulama"),
        P(
            "1 Mart 2026 itibarıyla MFA, kimlik sağlayıcıya bağlı tüm sistemlerde zorunludur: e-posta, VPN, "
            "kurumsal mesajlaşma, kod deposu, CI/CD platformu, İK portalı, finans uygulamaları ve NebulaCRM "
            "yönetim konsolu dahil. SMS ile tek kullanımlık kod, yalnızca yedek yöntem olarak ve en fazla "
            "7 gün süreyle kullanılabilir."
        ),
        P(
            "Yönetici (privileged) hesaplar için FIDO2 donanım güvenlik anahtarı zorunludur. Her yöneticiye "
            "biri yedek olmak üzere iki anahtar teslim edilir. Kayıp anahtar 24 saat içinde BT Yardım Masası'na "
            "bildirilmeli ve anahtar kimlik sağlayıcıdan derhal iptal edilmelidir."
        ),
        H1("5. Servis Hesapları ve Makine Sırları"),
        P(
            "Servis hesaplarının parolaları, API anahtarları ve sertifika özel anahtarları merkezi sır "
            "yönetim sistemi üzerinden dağıtılır. Servis hesabı sırları en geç 180 günde bir döndürülür; "
            "ödeme ve kimlik doğrulama hizmetlerine ait sırlar için bu süre 90 gündür. Sır döndürme işlemi "
            "çift anahtar yöntemiyle yapılır: yeni anahtar devreye alınıp tüm tüketiciler doğrulanmadan eski "
            "anahtar iptal edilmez. Bu kural, INC-2026-0417 kesintisinden çıkarılan dersler doğrultusunda "
            "Nisan 2026'da eklenmiş ve v2.0'ın 2.0.1 ara revizyonuyla duyurulmuştur."
        ),
        H1("6. Erişim Yaşam Döngüsü"),
        OL(
            "Erişim talepleri BT Portalı üzerinden açılır; talep, çalışanın yöneticisi ve ilgili sistem "
            "sahibi tarafından onaylanır.",
            "Geçici hesaplar (yüklenici, denetçi, stajyer) en fazla 30 gün için açılır ve süre sonunda "
            "otomatik olarak devre dışı kalır.",
            "İşten ayrılan çalışanın tüm hesapları, İK'nın ayrılış kaydını girmesinden itibaren en geç "
            "4 saat içinde devre dışı bırakılır.",
            "Departman değişikliğinde eski rol yetkileri 5 iş günü içinde kaldırılır.",
            "Ayrıcalıklı erişimler üç ayda bir, diğer erişimler yılda iki kez sistem sahipleri tarafından "
            "gözden geçirilir.",
        ),
        P(
            "Acil durum (break-glass) için iki adet yönetici hesabı tanımlıdır. Bu hesapların kimlik bilgileri "
            "Maslak genel merkezindeki kasada mühürlü zarfta saklanır, her kullanımda CEO Ofisi ve BT Müdürü "
            "bilgilendirilir ve hesaplar altı ayda bir test edilir."
        ),
        H1("7. v1.3 → v2.0 Değişiklik Özeti"),
        T(
            ("Kural", "v1.3 (2025)", "v2.0 (2026)"),
            (
                ("Minimum parola uzunluğu", "12 karakter", "14 karakter"),
                ("Periyodik değişim", "90 günde bir", "Yalnızca şüphe halinde"),
                ("Hesap kilitleme", "5 deneme / 30 dakika", "10 deneme / 15 dakika"),
                ("Parola geçmişi", "Son 5 parola", "Son 12 parola"),
                ("MFA kapsamı", "VPN ve e-posta", "Tüm sistemler"),
                ("Yönetici MFA yöntemi", "Mobil uygulama kodu", "FIDO2 güvenlik anahtarı"),
                ("Servis hesabı sırları", "Yılda bir", "180 günde bir"),
                ("Ekran kilidi", "15 dakika", "10 dakika"),
                ("Ayrılan çalışan hesabı", "24 saat içinde", "4 saat içinde"),
            ),
            caption="Tablo 1 — Sürümler arası başlıca farklar. v1.3, 1 Mart 2026 itibarıyla yürürlükten kalkmıştır.",
            widths=(2.4, 1.8, 1.8),
        ),
        H1("8. Uyum ve İstisnalar"),
        P(
            "Politikaya istisna talepleri, gerekçe ve telafi edici kontrollerle birlikte BT Portalı üzerinden "
            "Emre Kaya'ya iletilir. Onaylanan istisnalar en fazla 6 ay geçerlidir ve risk kaydına işlenir. "
            "Politikaya aykırılık, disiplin yönetmeliği çerçevesinde değerlendirilir. Uyum durumu her çeyrek "
            "sonunda Kalite Müdürlüğü'ne raporlanır; 2026 ilk çeyreğinde MFA kapsamı %99,2 olarak ölçülmüştür."
        ),
    ),
)

PASSWORD_V13 = Doc(
    path="bilgi-teknolojileri/Parola_Politikasi_v1.3_2025_ARSIV.txt",
    title="Parola Politikası (ARŞİV)",
    subtitle=(
        "ARŞİV KOPYASI — Bu sürüm 1 Mart 2026 tarihinde yürürlükten kaldırılmıştır. Güncel kurallar için "
        "BT-POL-002 Parola ve Erişim Yönetimi Politikası Sürüm 2.0'a bakınız."
    ),
    lang="tr",
    date=D(2025, 1, 10),
    doc_no="BT-POL-002",
    meta=(
        ("Sürüm", "1.3"),
        ("Sahibi", "Emre Kaya, BT Müdürü"),
        ("Onaylayan", "Mehmet Yılmaz, CEO"),
        ("Yürürlük", "15 Ocak 2025"),
        ("Yürürlükten kalkış", "1 Mart 2026 (yerini v2.0 almıştır)"),
    ),
    blocks=(
        H1("1. Amaç ve Kapsam"),
        P(
            "Bu politika, Nebula Teknoloji çalışanlarının ve yüklenicilerinin kurumsal sistemlere erişimde "
            "kullandığı parolaların oluşturulması, saklanması ve değiştirilmesine ilişkin asgari kuralları "
            "belirler. Politika İstanbul ve Ankara ofislerindeki tüm kullanıcılar ile uzaktan çalışanlar için "
            "geçerlidir. Sürüm 1.3, 2024 yılında yayımlanan v1.2'deki parola geçmişi ve kilitleme kurallarını "
            "güncellemek amacıyla hazırlanmıştır."
        ),
        H1("2. Parola Oluşturma"),
        UL(
            "Parolalar en az 12 karakter uzunluğunda olmalıdır.",
            "Parola; büyük harf, küçük harf, rakam ve özel karakterden en az üçünü içermelidir.",
            "Kullanıcı adı, ad-soyad, doğum tarihi veya şirket adı parolada kullanılamaz.",
            "Parola geçmişi son 5 parolayı tutar; bu parolalar yeniden kullanılamaz.",
        ),
        H1("3. Parola Değişimi"),
        P(
            "Kullanıcı parolaları 90 günde bir değiştirilmelidir. Süresi dolmadan 7 gün önce kullanıcıya "
            "e-posta ile hatırlatma gönderilir; süre dolduğunda ilk girişte parola değişimi zorunlu tutulur. "
            "Servis hesaplarının parolaları yılda bir kez, sistem sahibinin gözetiminde değiştirilir."
        ),
        H1("4. Hesap Kilitleme ve Oturum"),
        UL(
            "Art arda 5 hatalı denemeden sonra hesap 30 dakika süreyle kilitlenir.",
            "Kilit süresi dolmadan hesabın açılması için BT Yardım Masası'na kimlik doğrulamalı talep açılır.",
            "Ekran kilidi 15 dakika hareketsizlikten sonra devreye girer.",
        ),
        H1("5. Çok Faktörlü Kimlik Doğrulama"),
        P(
            "MFA yalnızca VPN bağlantılarında ve kurumsal e-posta erişiminde zorunludur. Diğer sistemlerde MFA "
            "kullanımı önerilir ancak zorunlu değildir. Yönetici hesaplarında ikinci faktör olarak mobil "
            "doğrulama uygulamasından üretilen tek kullanımlık kod kullanılır."
        ),
        H1("6. Parola Sıfırlama"),
        P(
            "Unutulan parolalar self-servis sıfırlama ekranından, kayıtlı cep telefonuna gönderilen kodla "
            "sıfırlanır. Self-servis sıfırlamanın mümkün olmadığı durumlarda kullanıcı BT Yardım Masası'nı arar; "
            "Yardım Masası, kullanıcının yöneticisinden teyit almadan parola sıfırlamaz. Geçici parolalar ilk "
            "girişte değiştirilmek zorundadır ve 24 saat sonra geçersiz olur."
        ),
        H1("7. Paylaşılan ve Servis Hesapları"),
        P(
            "Birden fazla kişi tarafından kullanılan paylaşılan hesaplar yalnızca toplantı odası cihazları ve "
            "eğitim ortamları için açılabilir. Bu hesapların parolaları ekip parola kasasında tutulur ve hesabı "
            "kullanan kişilerden biri ayrıldığında derhal değiştirilir. Servis hesapları etkileşimli girişe "
            "kapatılır; parolaları yılda bir kez değiştirilir ve değişiklik değişiklik yönetimi kaydıyla belgelenir."
        ),
        H1("8. Hesap Kapatma"),
        P(
            "İşten ayrılan çalışanın hesapları, ayrılış gününü izleyen 24 saat içinde BT ekibi tarafından "
            "kapatılır. Yüklenici hesapları sözleşme bitiş tarihinde devre dışı bırakılır. Kapatılan hesaplara "
            "ait e-posta kutuları 90 gün süreyle yöneticinin erişimine açık tutulur."
        ),
        H1("9. Sorumluluklar"),
        T(
            ("Rol", "Sorumluluk"),
            (
                ("Kullanıcı", "Parolayı gizli tutmak, 90 günde bir değiştirmek"),
                ("Yönetici", "Ekip erişimlerini yılda bir onaylamak"),
                ("BT Yardım Masası", "Kilit açma ve sıfırlama taleplerini doğrulamak"),
                ("BT Müdürü", "Politikanın sahibi ve yıllık gözden geçirme"),
            ),
        ),
        H1("10. Arşiv Notu"),
        P(
            "Bu belge yalnızca kayıt amacıyla saklanmaktadır. 2025 yılı iç denetiminde zorunlu 90 günlük "
            "değişimin zayıf ve ardışık parolalara yol açtığı tespit edilmiş, bu nedenle politika "
            "16 Şubat 2026 tarihinde yayımlanan ve 1 Mart 2026'da yürürlüğe giren Sürüm 2.0 ile tamamen "
            "yenilenmiştir. Bu arşiv kopyasındaki kurallar artık uygulanmaz."
        ),
    ),
)

LAPTOPS = (
    (
        "NB-LT-0007",
        "NB-14P",
        "Mehmet Yılmaz",
        "CEO Ofisi",
        "İstanbul",
        "14.02.2024",
        "14.02.2027",
        "Kullanımda",
    ),
    (
        "NB-LT-0012",
        "NB-14P",
        "Zeynep Şahin",
        "CEO Ofisi",
        "İstanbul",
        "14.02.2024",
        "14.02.2027",
        "Kullanımda",
    ),
    (
        "NB-LT-0019",
        "NB-16X",
        "Ayşe Demir",
        "Ar-Ge",
        "İstanbul",
        "03.04.2023",
        "03.04.2026",
        "Garanti dışı",
    ),
    (
        "NB-LT-0033",
        "NB-14P",
        "Emre Kaya",
        "Bilgi Teknolojileri",
        "İstanbul",
        "20.06.2023",
        "20.06.2026",
        "Yenileme planlandı",
    ),
    (
        "NB-LT-0057",
        "NB-14P",
        "Ali Vural",
        "Finans",
        "İstanbul",
        "05.09.2023",
        "05.09.2026",
        "Garanti dışı",
    ),
    (
        "NB-LT-0063",
        "NB-14P",
        "Elif Aydın",
        "Hukuk ve Uyum",
        "İstanbul",
        "05.09.2023",
        "05.09.2026",
        "Garanti dışı",
    ),
    (
        "NB-LT-0071",
        "NB-14P",
        "Burak Çelik",
        "İnsan Kaynakları",
        "İstanbul",
        "12.10.2023",
        "12.10.2026",
        "Kullanımda",
    ),
    (
        "NB-LT-0079",
        "NB-14P",
        "Selin Arslan",
        "Kalite Yönetimi",
        "İstanbul",
        "12.10.2023",
        "12.10.2026",
        "Kullanımda",
    ),
    (
        "NB-LT-0081",
        "NB-14P",
        "Can Öztürk",
        "Müşteri Deneyimi",
        "İstanbul",
        "12.10.2023",
        "12.10.2026",
        "Kullanımda",
    ),
    (
        "NB-LT-0084",
        "NB-14P",
        "Deniz Koç",
        "Pazarlama ve Satış",
        "İstanbul",
        "12.10.2023",
        "12.10.2026",
        "Kullanımda",
    ),
    (
        "NB-LT-0086",
        "NB-14P",
        "Merve Doğan",
        "Ürün Yönetimi",
        "İstanbul",
        "12.10.2023",
        "12.10.2026",
        "Kullanımda",
    ),
    (
        "NB-LT-0088",
        "NB-16X",
        "Murat Şen",
        "Bilgi Teknolojileri",
        "İstanbul",
        "08.01.2024",
        "08.01.2027",
        "Kullanımda",
    ),
    (
        "NB-LT-0090",
        "NB-16X",
        "Ece Polat",
        "Bilgi Teknolojileri",
        "Ankara",
        "08.01.2024",
        "08.01.2027",
        "Kullanımda",
    ),
    (
        "NB-LT-0118",
        "NB-14P",
        "—",
        "Pazarlama ve Satış",
        "İstanbul",
        "22.03.2024",
        "22.03.2027",
        "Kayıp (uzaktan silindi)",
    ),
    (
        "NB-LT-0142",
        "NB-16X",
        "Okan Yıldız",
        "Ar-Ge",
        "Ankara",
        "11.09.2024",
        "11.09.2027",
        "Kullanımda",
    ),
    (
        "NB-LT-0151",
        "NB-16X",
        "Gizem Aksoy",
        "Ar-Ge",
        "İstanbul",
        "11.09.2024",
        "11.09.2027",
        "Kullanımda",
    ),
    (
        "NB-LT-0168",
        "NB-14P",
        "Buse Erdoğan",
        "Finans",
        "İstanbul",
        "15.11.2024",
        "15.11.2027",
        "Kullanımda",
    ),
    (
        "NB-LT-0171",
        "NB-14P",
        "Tolga Yıldırım",
        "Finans",
        "İstanbul",
        "15.11.2024",
        "15.11.2027",
        "Kullanımda",
    ),
    (
        "NB-LT-0177",
        "NB-14P",
        "Naz Kurt",
        "Hukuk ve Uyum",
        "İstanbul",
        "15.11.2024",
        "15.11.2027",
        "Kullanımda",
    ),
    (
        "NB-LT-0181",
        "NB-14P",
        "Onur Aslan",
        "Hukuk ve Uyum",
        "İstanbul",
        "15.11.2024",
        "15.11.2027",
        "Kullanımda",
    ),
    (
        "NB-LT-0186",
        "NB-14P",
        "Sıla Çetin",
        "İnsan Kaynakları",
        "İstanbul",
        "07.01.2025",
        "07.01.2028",
        "Kullanımda",
    ),
    (
        "NB-LT-0190",
        "NB-14P",
        "Pınar Yalçın",
        "Kalite Yönetimi",
        "İstanbul",
        "07.01.2025",
        "07.01.2028",
        "Kullanımda",
    ),
    (
        "NB-LT-0192",
        "NB-16X",
        "Hakan Bulut",
        "Kalite Yönetimi",
        "Ankara",
        "07.01.2025",
        "07.01.2028",
        "Kullanımda",
    ),
    (
        "NB-LT-0196",
        "NB-14P",
        "Efe Taş",
        "Müşteri Deneyimi",
        "İstanbul",
        "18.03.2025",
        "18.03.2028",
        "Kullanımda",
    ),
    (
        "NB-LT-0199",
        "NB-14P",
        "Cansu Aydın",
        "Pazarlama ve Satış",
        "İstanbul",
        "18.03.2025",
        "18.03.2028",
        "Kullanımda",
    ),
    (
        "NB-LT-0201",
        "NB-14P",
        "Mert Özdemir",
        "Pazarlama ve Satış",
        "İstanbul",
        "18.03.2025",
        "18.03.2028",
        "Kullanımda",
    ),
    (
        "NB-LT-0203",
        "NB-14P",
        "İrem Korkmaz",
        "Ürün Yönetimi",
        "İstanbul",
        "18.03.2025",
        "18.03.2028",
        "Kullanımda",
    ),
    (
        "NB-LT-0204",
        "NB-13L",
        "Kerem Acar",
        "CEO Ofisi",
        "İstanbul",
        "18.03.2025",
        "18.03.2028",
        "Kullanımda",
    ),
    (
        "NB-LT-0207",
        "NB-16X",
        "Yusuf Eren",
        "Ürün Yönetimi",
        "İstanbul",
        "02.06.2025",
        "02.06.2028",
        "Kullanımda",
    ),
    (
        "NB-LT-0233",
        "NB-13L",
        "Berk Güneş",
        "İnsan Kaynakları",
        "İstanbul",
        "25.08.2025",
        "25.08.2028",
        "Kullanımda",
    ),
    (
        "NB-LT-0241",
        "NB-13L",
        "Derya Kılıç",
        "Müşteri Deneyimi",
        "İzmir",
        "25.08.2025",
        "25.08.2028",
        "Kullanımda",
    ),
    (
        "NB-LT-0252",
        "NB-14P",
        "—",
        "Nebula Technology GmbH",
        "Berlin",
        "19.01.2026",
        "19.01.2029",
        "Kullanımda",
    ),
    (
        "NB-LT-0259",
        "NB-14P",
        "Havuz (yedek)",
        "Bilgi Teknolojileri",
        "İstanbul",
        "10.07.2026",
        "10.07.2029",
        "Depoda",
    ),
    (
        "NB-LT-0260",
        "NB-16X",
        "Havuz (yedek)",
        "Bilgi Teknolojileri",
        "İstanbul",
        "10.07.2026",
        "10.07.2029",
        "Depoda",
    ),
    (
        "NB-LT-0261",
        "NB-13L",
        "Havuz (yedek)",
        "Bilgi Teknolojileri",
        "İzmir",
        "10.07.2026",
        "10.07.2029",
        "Depoda",
    ),
    (
        "NB-LT-0262",
        "NB-13L",
        "Havuz (yedek)",
        "Bilgi Teknolojileri",
        "İzmir",
        "10.07.2026",
        "10.07.2029",
        "Depoda",
    ),
)

INVENTORY = Doc(
    path="bilgi-teknolojileri/BT_Varlik_Envanteri_2026.xlsx",
    title="BT Varlık Envanteri 2026",
    lang="tr",
    date=D(2026, 9, 30),
    sheets=(
        Sheet(
            name="Özet",
            title="BT Varlık Envanteri — Sayım tarihi 30.09.2026",
            header=("Kategori", "Model / Konum", "Adet", "Açıklama"),
            rows=(
                (
                    "Dizüstü bilgisayar",
                    "NB-14P (14 inç, 32 GB RAM)",
                    148,
                    "Standart çalışan cihazı",
                ),
                (
                    "Dizüstü bilgisayar",
                    "NB-16X (16 inç, 64 GB RAM)",
                    71,
                    "Ar-Ge, veri ve tasarım ekipleri",
                ),
                (
                    "Dizüstü bilgisayar",
                    "NB-13L (13 inç, 16 GB RAM)",
                    43,
                    "İzmir destek merkezi ve stajyerler",
                ),
                ("Dizüstü bilgisayar", "Toplam", 262, "Yenileme döngüsü 4 yıl"),
                (
                    "Monitör",
                    "27 inç QHD ve 24 inç FHD",
                    318,
                    "Ofis masaları ve ev-ofis kurulumları",
                ),
                ("Yerleştirme istasyonu", "DK-200", 205, "İstanbul ve Ankara ofisleri"),
                ("Kurumsal mobil telefon", "MP-6", 64, "Nöbetçi ekipler ve yöneticiler"),
                ("FIDO2 güvenlik anahtarı", "FK-2", 96, "48 yönetici hesabı, kişi başı 2 adet"),
                ("Sunucu", "IST-1 (İstanbul)", 46, "Birincil veri merkezi"),
                ("Sunucu", "ANK-DR1 (Ankara)", 18, "Felaket kurtarma sahası"),
                ("Sunucu", "FRA-1 (Frankfurt)", 12, "AB bölgesi, 1 Temmuz 2026'dan beri canlı"),
                ("Ağ anahtarı", "SW-48", 22, "Ofisler ve veri merkezleri"),
                ("Güvenlik duvarı", "FW-HA çifti", 6, "Her sahada yüksek erişilebilir çift"),
                (
                    "Toplantı odası video sistemi",
                    "VC-Room",
                    19,
                    "İstanbul 11, Ankara 4, İzmir 3, Berlin 1",
                ),
                ("Ağ yazıcısı", "PR-MF", 7, "Kartlı baskı, misafir ağına kapalı"),
            ),
            notes=(
                "Hazırlayan: Murat Şen (Sistem Yöneticisi). Onaylayan: Emre Kaya (BT Müdürü).",
                "Dizüstü bilgisayarlar satın alma tarihinden itibaren 4 yılda bir yenilenir; garanti süresi 3 yıldır.",
                "Bir sonraki fiziksel sayım: 31.03.2027.",
            ),
            widths=(28, 30, 8, 46),
        ),
        Sheet(
            name="Dizüstü Bilgisayarlar",
            header=(
                "Demirbaş No",
                "Model",
                "Kullanıcı",
                "Departman",
                "Lokasyon",
                "Satın Alma Tarihi",
                "Garanti Bitişi",
                "Durum",
            ),
            rows=LAPTOPS,
            notes=(
                (
                    "Liste, 262 cihazlık envanterin yönetim ekibi, departman temsilcileri ve depo stoğuna ait kesitidir; "
                    "tam liste uç nokta yönetim sisteminden alınır."
                ),
                "NB-LT-0118 için 12.07.2026 tarihinde kayıp bildirimi yapılmış, cihaz aynı gün uzaktan silinmiştir.",
            ),
        ),
        Sheet(
            name="Sunucular",
            header=(
                "Grup Kodu",
                "Saha",
                "Rol",
                "Adet",
                "Toplam CPU Çekirdeği",
                "Toplam RAM (GB)",
                "Devreye Alma",
                "Sorumlu",
            ),
            rows=(
                (
                    "IST1-K8S-W",
                    "IST-1",
                    "Kubernetes çalışan düğümü",
                    24,
                    1536,
                    12288,
                    "03.2024",
                    "Ece Polat",
                ),
                (
                    "IST1-K8S-CP",
                    "IST-1",
                    "Kubernetes kontrol düzlemi",
                    3,
                    96,
                    384,
                    "03.2024",
                    "Ece Polat",
                ),
                (
                    "IST1-PG",
                    "IST-1",
                    "PostgreSQL (birincil + 2 replika)",
                    3,
                    192,
                    1536,
                    "09.2025",
                    "Murat Şen",
                ),
                (
                    "IST1-PG-DED",
                    "IST-1",
                    "PostgreSQL özel kiracı kümeleri",
                    3,
                    144,
                    1152,
                    "02.2026",
                    "Murat Şen",
                ),
                ("IST1-KAFKA", "IST-1", "Kafka aracısı", 3, 96, 384, "03.2024", "Ece Polat"),
                ("IST1-REDIS", "IST-1", "Redis önbellek", 3, 48, 768, "03.2024", "Ece Polat"),
                ("IST1-OBJ", "IST-1", "Nesne depolama", 5, 80, 640, "06.2024", "Murat Şen"),
                ("IST1-MGMT", "IST-1", "Bastion ve yönetim", 2, 32, 128, "03.2024", "Murat Şen"),
                (
                    "ANK-K8S-W",
                    "ANK-DR1",
                    "Kubernetes çalışan düğümü",
                    8,
                    512,
                    4096,
                    "11.2024",
                    "Ece Polat",
                ),
                (
                    "ANK-PG",
                    "ANK-DR1",
                    "PostgreSQL bekleme kümesi",
                    3,
                    192,
                    1536,
                    "11.2024",
                    "Murat Şen",
                ),
                (
                    "ANK-OBJ",
                    "ANK-DR1",
                    "Nesne depolama (replika)",
                    4,
                    64,
                    512,
                    "11.2024",
                    "Murat Şen",
                ),
                (
                    "ANK-KAFKA",
                    "ANK-DR1",
                    "Kafka aracısı (ayna)",
                    3,
                    96,
                    384,
                    "11.2024",
                    "Ece Polat",
                ),
                (
                    "FRA-K8S-W",
                    "FRA-1",
                    "Kubernetes çalışan düğümü",
                    6,
                    384,
                    3072,
                    "06.2026",
                    "Ece Polat",
                ),
                (
                    "FRA-PG",
                    "FRA-1",
                    "PostgreSQL (birincil + 2 replika)",
                    3,
                    192,
                    1536,
                    "06.2026",
                    "Murat Şen",
                ),
                ("FRA-OBJ", "FRA-1", "Nesne depolama", 3, 48, 384, "06.2026", "Murat Şen"),
            ),
            notes=("Saha toplamları: IST-1 46 sunucu, ANK-DR1 18 sunucu, FRA-1 12 sunucu.",),
        ),
        Sheet(
            name="Yazılım Lisansları",
            header=(
                "Yazılım (genel ad)",
                "Kullanım Amacı",
                "Lisans Türü",
                "Koltuk / Adet",
                "Yıllık Maliyet (TL)",
                "Yenileme Tarihi",
                "Sistem Sahibi",
            ),
            rows=(
                (
                    "Kurumsal parola kasası",
                    "Parola ve sır saklama",
                    "Kullanıcı başı abonelik",
                    270,
                    486000,
                    "01.03.2027",
                    "Emre Kaya",
                ),
                (
                    "Uç nokta güvenlik ajanı (EDR)",
                    "Zararlı yazılım tespiti",
                    "Cihaz başı abonelik",
                    280,
                    1176000,
                    "15.01.2027",
                    "Emre Kaya",
                ),
                (
                    "Mobil cihaz yönetimi (MDM)",
                    "Dizüstü ve telefon yönetimi",
                    "Cihaz başı abonelik",
                    330,
                    396000,
                    "15.01.2027",
                    "Murat Şen",
                ),
                (
                    "Ofis üretkenlik paketi",
                    "E-posta, belge, takvim",
                    "Kullanıcı başı abonelik",
                    260,
                    2340000,
                    "01.02.2027",
                    "Murat Şen",
                ),
                (
                    "Kurumsal mesajlaşma",
                    "Ekip içi iletişim",
                    "Kullanıcı başı abonelik",
                    260,
                    819000,
                    "01.02.2027",
                    "Murat Şen",
                ),
                (
                    "Video konferans",
                    "Toplantı ve webinar",
                    "Kullanıcı başı abonelik",
                    260,
                    624000,
                    "01.02.2027",
                    "Murat Şen",
                ),
                (
                    "Kod deposu ve CI/CD platformu",
                    "Kaynak kod ve derleme",
                    "Kullanıcı başı abonelik",
                    140,
                    1512000,
                    "30.04.2027",
                    "Ece Polat",
                ),
                (
                    "Hata ve iş takip sistemi",
                    "Ürün geliştirme takibi",
                    "Kullanıcı başı abonelik",
                    185,
                    832500,
                    "30.04.2027",
                    "Ece Polat",
                ),
                (
                    "Gözlemlenebilirlik platformu",
                    "Log, metrik, izleme",
                    "Veri hacmi bazlı",
                    1,
                    2160000,
                    "01.06.2027",
                    "Ece Polat",
                ),
                (
                    "SIEM ve olay korelasyonu",
                    "Güvenlik izleme",
                    "Veri hacmi bazlı",
                    1,
                    1380000,
                    "01.01.2027",
                    "Emre Kaya",
                ),
                (
                    "Zafiyet tarayıcı",
                    "Altyapı ve uygulama taraması",
                    "Varlık bazlı",
                    500,
                    420000,
                    "01.09.2027",
                    "Emre Kaya",
                ),
                (
                    "Yedekleme yazılımı",
                    "Veritabanı ve dosya yedekleri",
                    "Kapasite bazlı (TB)",
                    180,
                    945000,
                    "01.11.2026",
                    "Murat Şen",
                ),
                (
                    "Tasarım aracı",
                    "Arayüz tasarımı",
                    "Kullanıcı başı abonelik",
                    12,
                    172800,
                    "01.03.2027",
                    "Merve Doğan",
                ),
                (
                    "Diyagram ve beyaz tahta aracı",
                    "Mimari çizimler",
                    "Kullanıcı başı abonelik",
                    45,
                    81000,
                    "01.03.2027",
                    "Ayşe Demir",
                ),
                (
                    "Elektronik imza sertifikası",
                    "Sözleşme ve resmi yazışma",
                    "Kişi başı sertifika",
                    18,
                    27000,
                    "01.12.2026",
                    "Elif Aydın",
                ),
                (
                    "Muhasebe ve ERP yazılımı",
                    "Finans ve bordro",
                    "Kullanıcı başı lisans",
                    14,
                    588000,
                    "01.01.2027",
                    "Ali Vural",
                ),
            ),
            notes=("Tutarlar KDV hariçtir ve 2026 sözleşme bedellerini gösterir.",),
        ),
    ),
)

BACKUP_DR = Doc(
    path="bilgi-teknolojileri/Yedekleme_ve_Felaket_Kurtarma_Plani.docx",
    title="Yedekleme ve Felaket Kurtarma Planı",
    subtitle="NebulaCRM üretim ortamı ve kurumsal sistemler",
    lang="tr",
    date=D(2026, 6, 15),
    doc_no="BT-PLN-005",
    meta=(
        ("Sürüm", "3.2"),
        ("Sahibi", "Emre Kaya, BT Müdürü"),
        ("Hazırlayanlar", "Ece Polat (DevOps Mühendisi), Murat Şen (Sistem Yöneticisi)"),
        ("Onaylayan", "Mehmet Yılmaz, CEO"),
        ("Gözden geçirme sıklığı", "Yılda bir ve her büyük olay sonrasında"),
    ),
    blocks=(
        H1("1. Amaç ve Kapsam"),
        P(
            "Bu plan, NebulaCRM üretim ortamındaki müşteri verisinin ve kurumsal sistemlerin yedeklenmesi, "
            "geri yüklenmesi ve bir felaket durumunda hizmetin yedek sahada yeniden ayağa kaldırılması için "
            "uygulanacak yöntemleri tanımlar. Kapsam; İstanbul'daki birincil veri merkezi IST-1, Ankara'daki "
            "felaket kurtarma sahası ANK-DR1 ve 1 Temmuz 2026'da canlıya alınan Frankfurt bölgesi FRA-1'deki "
            "PostgreSQL kümelerini, nesne depolamayı, Kafka olay akışlarını ve yapılandırma depolarını kapsar."
        ),
        H1("2. Hedefler"),
        P(
            "Tüm planlar için kurtarma noktası hedefi (RPO) 15 dakika, kurtarma süresi hedefi (RTO) 4 saattir. "
            "Kurumsal Plus müşterilerine ayrılmış özel veritabanı kümeleri için RTO 2 saattir. Bu hedefler "
            "müşteri sözleşmelerindeki taahhütlerin temelini oluşturur ve her DR testinde ölçülür."
        ),
        H1("3. Yedekleme Yöntemi"),
        H2("3.1 Veritabanı"),
        P(
            "PostgreSQL kümelerinde sürekli WAL arşivleme kullanılır; WAL segmentleri en geç 60 saniyede bir "
            "nesne depolamaya gönderilir. Her gün saat 02:00'de (TSİ) tam anlık görüntü (snapshot) alınır. "
            "Günlük yedekler 35 gün, aylık yedekler 12 ay saklanır. Yedekler AES-256 ile şifrelenir; şifreleme "
            "anahtarları donanım güvenlik modülünde tutulur ve yedeklerle aynı sahada saklanmaz."
        ),
        P(
            "INC-2026-0417 kesintisinin ardından iki yeni izleme kuralı eklenmiştir: WAL arşiv gecikmesi "
            "10 dakikayı aştığında nöbetçi mühendis çağrılır ve veritabanı disk doluluk alarm eşiği %90'dan "
            "%75'e indirilmiştir. Arşivleme komutunun her başarısız denemesi artık hata günlüğüne ve metrik "
            "sistemine yazılır."
        ),
        H2("3.2 Nesne depolama ve dosyalar"),
        P(
            "Müşteri eklentileri ve dışa aktarma dosyaları IST-1'den ANK-DR1'e asenkron olarak çoğaltılır; "
            "çoğaltma gecikmesi hedefi 5 dakikadır. Yedek kovaları 35 gün boyunca değiştirilemez (object lock) "
            "modda tutulur. FRA-1 verileri Avrupa Birliği dışına kopyalanmaz; FRA-1 yedekleri aynı bölgedeki "
            "ayrı bir veri salonunda saklanır."
        ),
        H2("3.3 Yapılandırma ve kod"),
        P(
            "Altyapı tanımları, Kubernetes manifestleri ve uygulama yapılandırmaları sürüm kontrol sisteminde "
            "tutulur ve her gece ANK-DR1'deki depo aynasına kopyalanır. Gizli anahtarlar yedeklere dahil "
            "edilmez; sır yönetim sistemi kendi çapraz saha çoğaltmasına sahiptir."
        ),
        H1("4. Geri Yükleme Testleri"),
        P(
            "Her ayın ilk çarşamba günü, rastgele seçilen bir kiracının verisi izole bir ortama geri yüklenir ve "
            "kayıt sayıları üretimle karşılaştırılır. 2026'nın ilk beş ayında yapılan beş testin tamamı başarılı "
            "olmuş, ortalama geri yükleme süresi 38 dakika olarak ölçülmüştür."
        ),
        H1("5. Felaket İlanı ve Roller"),
        OL(
            "Felaket ilanı yetkisi BT Müdürü Emre Kaya'dadır; ulaşılamadığında yetki DevOps Mühendisi Ece Polat'a geçer.",
            "Teknik kurtarmayı nöbetçi SRE ekibi yürütür; veritabanı geçişinden Murat Şen sorumludur.",
            "Müşteri iletişimini Müşteri Deneyimi Müdürü Can Öztürk koordine eder; ilk duyuru 30 dakika içinde "
            "status.nebulacrm.example adresinde yayımlanır.",
            "CEO Mehmet Yılmaz, 1 saati aşacağı öngörülen her felaket ilanında bilgilendirilir.",
        ),
        H1("6. Kurtarma Sırası"),
        P(
            "Felaket ilanından sonra hizmetler aşağıdaki sırayla ANK-DR1'de ayağa kaldırılır. Her adım, bir "
            "önceki adımın sağlık kontrolleri başarılı olmadan başlatılmaz; adımların tamamı DR çalışma kitabında "
            "komut düzeyinde belgelenmiştir."
        ),
        OL(
            "DNS ve yük dengeleyici kayıtlarının ANK-DR1'e yönlendirilmesi (hedef: 10 dakika).",
            "PostgreSQL bekleme kümesinin birincil olarak yükseltilmesi ve son WAL segmentlerinin uygulanması.",
            "Kimlik doğrulama, kiracı yönetimi ve faturalama servislerinin başlatılması.",
            "Kafka aynasının birincil hale getirilmesi ve olay tüketicilerinin yeniden başlatılması.",
            "Web uygulaması, genel API ve webhook gönderim servislerinin trafiğe açılması.",
            "Raporlama, NebulaAnalytics ve Nebula Assist gibi kritik olmayan servislerin açılması.",
        ),
        P(
            "Kurtarma sırasında yalnızca okunur kip ilan edilebilir: veritabanı yükseltmesi 2 saati aşacak "
            "olursa müşterilerin verilerini görüntüleyebilmesi için uygulama okunur kipte açılır ve durum sayfasında "
            "duyurulur."
        ),
        H1("7. DR Testleri"),
        P(
            "DR testleri yılda iki kez, mayıs ve kasım aylarında yapılır. Testte IST-1'in tamamen kaybedildiği "
            "varsayılır ve üretim trafiği ANK-DR1'e taşınır. Son test 23 Mayıs 2026'da yapılmış ve gerçekleşen "
            "RTO 2 saat 41 dakika olmuştur. Bir sonraki test 21 Kasım 2026 tarihinde planlanmıştır."
        ),
        P(
            "DR test kayıtları BT Müdürü Emre Kaya tarafından imzalanarak onaylanır. 23 Mayıs 2026 testine ait "
            "kayıt, 9–11 Haziran 2026'daki ISO/IEC 27001 gözetim denetiminde imza eksikliği nedeniyle minör "
            "uygunsuzluk konusu olmuş; kayıt 12 Haziran 2026'da Emre Kaya tarafından imzalanmıştır. Bundan "
            "sonra test raporu, imza tamamlanmadan kapatılamayacak şekilde iş akışına bağlanmıştır."
        ),
        T(
            ("Test tarihi", "Senaryo", "Hedef RTO", "Gerçekleşen RTO", "Gerçekleşen RPO", "Onay"),
            (
                (
                    "17.05.2025",
                    "IST-1 tam kayıp",
                    "4 saat",
                    "3 saat 52 dakika",
                    "11 dakika",
                    "Emre Kaya",
                ),
                (
                    "15.11.2025",
                    "Birincil PostgreSQL kaybı",
                    "4 saat",
                    "3 saat 18 dakika",
                    "9 dakika",
                    "Emre Kaya",
                ),
                (
                    "23.05.2026",
                    "IST-1 tam kayıp",
                    "4 saat",
                    "2 saat 41 dakika",
                    "6 dakika",
                    "Emre Kaya (12.06.2026)",
                ),
                ("21.11.2026", "IST-1 tam kayıp + Kafka", "4 saat", "Planlandı", "Planlandı", "—"),
            ),
            caption="Tablo 1 — DR test geçmişi ve planı",
        ),
        H1("8. Revizyon Geçmişi"),
        T(
            ("Sürüm", "Tarih", "Değişiklik"),
            (
                ("3.0", "10.01.2026", "FRA-1 bölgesi kapsama eklendi"),
                ("3.1", "05.05.2026", "INC-2026-0417 sonrası WAL gecikme ve disk alarmları"),
                ("3.2", "15.06.2026", "DR kaydı imza iş akışı; Mayıs 2026 test sonuçları"),
            ),
        ),
    ),
)

POSTMORTEM = Doc(
    path="bilgi-teknolojileri/Postmortem_INC-2026-0417_Database_Outage.pdf",
    title="Postmortem: INC-2026-0417 Primary Database Outage",
    subtitle="Blameless incident review — NebulaCRM production (IST-1)",
    lang="en",
    date=D(2026, 5, 20),
    doc_no="SRE-PM-2026-004",
    meta=(
        ("Severity", "Sev-1"),
        ("Incident commander", "Ece Polat, DevOps Engineer"),
        ("Author", "Ece Polat"),
        ("Reviewed by", "Emre Kaya (IT Manager), Ayşe Demir (R&D Manager)"),
        ("Review meeting", "24 April 2026"),
        ("Status", "Final (action items updated 20 May 2026)"),
    ),
    blocks=(
        H1("1. Summary"),
        P(
            "On 17 April 2026, from 09:12 to 11:59 TRT (167 minutes), the primary PostgreSQL cluster in IST-1 "
            "stopped accepting writes. WAL archiving had stalled the previous evening after an object-storage "
            "credential rotation; un-archived WAL segments accumulated until the primary's data volume filled "
            "up, and the cluster manager fenced the primary into read-only mode to protect data integrity. "
            "During the incident 38% of API requests failed with 5xx errors and 286 customer accounts were "
            "affected. No customer data was lost."
        ),
        P(
            "This was our most serious production incident since INC-2025-1107 on 7 November 2025, a 52-minute "
            "Sev-2 outage caused by a DNS change on the load balancer. Unlike that incident, the trigger here "
            "was a routine change whose side effect was invisible to our monitoring for almost 15 hours."
        ),
        H1("2. Impact"),
        UL(
            "Duration: 167 minutes of degraded service (09:12–11:59 TRT).",
            "38% of API requests failed; web application writes (creating or updating records) failed for all "
            "tenants on the shared cluster, while most reads continued to work from replicas.",
            "286 customer accounts were affected. Tenants on dedicated Kurumsal Plus clusters were not affected.",
            "Outbound webhooks were delayed by up to 3 hours 10 minutes and were delivered through the normal "
            "retry schedule; no webhook was dropped.",
            "Monthly uptime for April 2026 was 99.61% for the shared production cluster.",
            "61 Kurumsal and Kurumsal Plus customers were eligible for service credits totalling TRY 1.24M. "
            "Credits were calculated according to the service-credit tiers in the 2026 support SLA matrix.",
        ),
        H1("3. Timeline (TRT)"),
        T(
            ("Time", "Event"),
            (
                ("16 Apr 18:30", "Backup bucket credentials rotated (change CHG-2026-0388)"),
                ("16 Apr 18:31", "archive_command starts failing; failures retried silently"),
                (
                    "17 Apr 08:47",
                    "Primary disk passes 90% warning; alert goes to low-priority channel",
                ),
                ("17 Apr 09:12", "Data volume full; primary fenced read-only; write errors begin"),
                ("17 Apr 09:16", "On-call paged by API 5xx alert"),
                ("17 Apr 09:21", "Sev-1 declared"),
                ("17 Apr 09:24", "Ece Polat takes the incident commander role"),
                ("17 Apr 09:31", "First status page update published"),
                ("17 Apr 09:58", "Root cause identified: WAL archiving stalled"),
                ("17 Apr 10:20", "Archiver restored with new credentials; backlog draining"),
                ("17 Apr 11:05", "Disk usage below 80%; writes re-enabled on primary"),
                ("17 Apr 11:59", "Error rates back to baseline; incident mitigated"),
                ("17 Apr 14:30", "Incident resolved on status page; customer summary sent"),
            ),
            widths=(1.0, 4.6),
        ),
        H1("4. Root Cause"),
        P(
            "The backup bucket's access keys were rotated at 18:30 on 16 April as part of the quarterly key "
            "rotation. The rotation runbook updated the credentials used by the backup jobs but not the "
            "separate credential file read by PostgreSQL's archive_command on the primary. From 18:31 every "
            "archive attempt failed with an authorisation error. PostgreSQL correctly kept the un-archived WAL "
            "segments on local disk, so no data was at risk, but the volume grew by roughly 4% per hour."
        ),
        P(
            "Three conditions turned this into an outage. First, archive_command failures were not exported as "
            "a metric, so nothing alerted on growing archive lag. Second, the disk usage alert fired at 90% at "
            "08:47 but was routed to a non-paging channel. Third, the old and new keys were not valid in "
            "parallel, so the rotation broke any consumer that had not been updated in the same minute."
        ),
        H1("5. What Went Well"),
        UL(
            "Detection of customer impact took 4 minutes from the first write error to the page.",
            "Replicas kept serving reads, so most dashboards and searches stayed available.",
            "Customer communication followed the Sev-1 template; the first status update went out 19 minutes "
            "after impact began.",
        ),
        H1("6. Detection and Response Analysis"),
        P(
            "Time to detect customer impact was good, but time to detect the underlying fault was poor: the "
            "archiver had been failing for 14 hours and 41 minutes before the first write error. Responders spent "
            "the first 34 minutes treating the incident as a database capacity problem and attempted to extend the "
            "volume online, which bought about 20 minutes of writes before the volume filled again. The diagnosis "
            "changed at 09:58, when Murat Şen compared the archive status view with the replication lag dashboard "
            "and noticed that the last successfully archived segment dated from 18:30 the previous day."
        ),
        P(
            "We deliberately did not fail over to a replica. Promoting a replica would not have cleared the WAL "
            "backlog on the old primary and would have risked a split-brain during the credential fix. In "
            "hindsight this was the right call: once the archiver had valid credentials, the backlog of roughly "
            "1,900 segments drained in 45 minutes and writes were re-enabled without a topology change."
        ),
        H1("7. Customer Communication"),
        P(
            "The status page at status.nebulacrm.example was updated six times during the incident. Account "
            "managers personally called the 12 largest affected customers, including two Kurumsal Plus accounts "
            "that asked for confirmation that their dedicated clusters were unaffected. A written summary of this "
            "postmortem was sent to all affected customer administrators on 30 April 2026. The support team "
            "handled 412 incident-related tickets on 17 and 18 April, about four times the normal daily volume."
        ),
        H1("8. Action Items"),
        T(
            ("ID", "Action", "Owner", "Due", "Status"),
            (
                ("AI-1", "Page on WAL archive lag > 10 min", "Murat Şen", "15 May 2026", "Done"),
                ("AI-2", "Disk alert 90% → 75%, paging", "Ece Polat", "30 Apr 2026", "Done"),
                (
                    "AI-3",
                    "Dual-key credential rotation runbook",
                    "Emre Kaya",
                    "31 May 2026",
                    "Done",
                ),
                (
                    "AI-4",
                    "Quarterly database failover game day",
                    "Ece Polat",
                    "30 Jun 2026",
                    "In progress",
                ),
                (
                    "AI-5",
                    "Export archive_command failures as metric",
                    "Okan Yıldız",
                    "15 May 2026",
                    "Done",
                ),
                (
                    "AI-6",
                    "Sev-1 customer notice within 30 min",
                    "Can Öztürk",
                    "15 May 2026",
                    "Done",
                ),
            ),
            widths=(0.6, 3.2, 1.3, 1.2, 1.0),
        ),
        H1("9. Lessons Learned"),
        P(
            "Routine changes deserve the same verification as feature releases: a credential rotation is only "
            "complete when every consumer has been confirmed on the new key. We also learned that a warning "
            "nobody is paged for is effectively not an alert. The dual-key rule from AI-3 has since been added "
            "to the IT password and access policy, and the backup and disaster recovery plan now lists the WAL "
            "lag and disk thresholds as mandatory monitoring."
        ),
    ),
)

DOCS = [PASSWORD_V2, PASSWORD_V13, INVENTORY, BACKUP_DR, POSTMORTEM]
