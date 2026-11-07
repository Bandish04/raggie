# SPDX-License-Identifier: Apache-2.0

"""Hukuk ve Uyum (legal & compliance) department documents."""

from model import H1, OL, UL, D, Doc, P, Sheet, T

KVKK = Doc(
    path="hukuk-uyum/KVKK_Kisisel_Veri_Saklama_ve_Imha_Politikasi.pdf",
    title="Kişisel Veri Saklama ve İmha Politikası",
    subtitle="6698 sayılı Kişisel Verilerin Korunması Kanunu kapsamında",
    lang="tr",
    date=D(2026, 1, 20),
    doc_no="HUK-POL-003",
    meta=(
        ("Sürüm", "2.1"),
        ("Sahibi", "Elif Aydın, Hukuk ve Uyum Müdürü"),
        ("Hazırlayan", "Onur Aslan, Uyum Uzmanı"),
        ("Onaylayan", "Mehmet Yılmaz, CEO"),
        ("Yürürlük", "1 Şubat 2026"),
    ),
    blocks=(
        H1("1. Amaç"),
        P(
            "Bu politika, Nebula Teknoloji A.Ş.'nin veri sorumlusu ve veri işleyen sıfatıyla işlediği kişisel "
            "verilerin hangi süreyle saklanacağını, saklama süresi dolan verilerin hangi yöntemlerle silineceğini, "
            "yok edileceğini veya anonim hale getirileceğini ve bu süreçlerde görev alacak birimleri belirler. "
            "Politika, Kişisel Verilerin Silinmesi, Yok Edilmesi veya Anonim Hale Getirilmesi Hakkında "
            "Yönetmelik'te öngörülen kişisel veri saklama ve imha politikası yükümlülüğünü karşılar."
        ),
        H1("2. Roller"),
        P(
            "Çalışan, aday, ziyaretçi ve tedarikçi verileri bakımından şirketimiz veri sorumlusudur. Müşterilerin "
            "NebulaCRM'e yüklediği kiracı verileri bakımından ise şirketimiz veri işleyen konumundadır; bu "
            "verilere ilişkin talimatlar müşteriyle imzalanan Veri İşleme Sözleşmesi ile belirlenir. Müşterilerimize "
            "karşı ihlal bildirimi, alt işleyen değişikliği ve denetim hakları gibi sözleşmesel yükümlülükler bu "
            "politikada değil, Veri İşleme Sözleşmesi'nde düzenlenmiştir."
        ),
        P(
            "Kurum adına Veri Sorumlusu İrtibat Kişisi Uyum Uzmanı Onur Aslan'dır. Kişisel verilerle ilgili tüm "
            "başvurular kvkk@nebulacrm.example adresine veya genel merkez adresine yazılı olarak iletilir ve en geç "
            "30 gün içinde ücretsiz olarak sonuçlandırılır. Şirket, Veri Sorumluları Sicil Bilgi Sistemi'ne "
            "(VERBİS) kayıtlıdır; kayıt bilgileri her yıl ocak ayında güncellenir."
        ),
        H1("3. Saklama Süreleri"),
        P(
            "Aşağıdaki tablo, başlıca kişisel veri kategorileri için azami saklama sürelerini gösterir. Bir veri "
            "birden fazla amaçla işleniyorsa en uzun yasal süre uygulanır. Süreler, ilgili sözleşmenin sona "
            "ermesi, çalışanın ayrılması veya başvurunun sonuçlanması gibi olayın gerçekleştiği tarihten itibaren "
            "işlemeye başlar."
        ),
        T(
            ("Veri kategorisi", "Saklama süresi", "Dayanak", "İmha yöntemi"),
            (
                ("Müşteri sözleşmeleri", "10 yıl", "Türk Ticaret Kanunu", "Silme"),
                (
                    "Kiracı CRM verileri",
                    "Sözleşme sonu + 90 gün",
                    "Veri İşleme Sözleşmesi",
                    "Kalıcı silme",
                ),
                ("Veritabanı yedekleri", "35 gün", "Teknik gereklilik", "Otomatik döngü"),
                ("Erişim kayıtları (loglar)", "2 yıl", "5651 sayılı Kanun", "Silme"),
                ("İş başvurusu CV'leri", "1 yıl", "Açık rıza", "Silme"),
                ("Personel özlük dosyası", "Ayrılış + 10 yıl", "İş Kanunu", "Silme ve imha"),
                ("Bordro kayıtları", "10 yıl", "Vergi mevzuatı", "Silme"),
                ("Güvenlik kamerası kayıtları", "30 gün", "Meşru menfaat", "Üzerine yazma"),
                ("Ziyaretçi giriş kayıtları", "1 yıl", "Meşru menfaat", "Silme"),
                ("Destek talepleri", "Kapanış + 3 yıl", "Sözleşme", "Anonimleştirme"),
                ("Ticari ileti onayları", "Onay sonu + 3 yıl", "6563 sayılı Kanun", "Silme"),
            ),
            caption="Tablo 1 — Kişisel veri kategorileri ve azami saklama süreleri",
            widths=(2.6, 2.1, 2.1, 1.5),
        ),
        P(
            "Kiracı CRM verileri, müşteri sözleşmesinin sona ermesinden 90 gün sonra üretim ortamından kalıcı "
            "olarak silinir; bu tarihten sonra veriler yedeklerde en fazla 35 gün daha kalır ve yedek döngüsüyle "
            "birlikte tamamen ortadan kalkar. Sözleşmenin sona ermesinden sonraki ilk 30 gün içinde müşteri, "
            "self-servis dışa aktarma aracıyla verilerini indirebilir."
        ),
        H1("4. İmha Yöntemleri"),
        UL(
            "Silme: Verinin ilgili kullanıcılar için hiçbir şekilde erişilemez ve tekrar kullanılamaz hale getirilmesi.",
            "Yok etme: Fiziksel ortamların (kağıt, disk) kırpma veya kriptografik silme sonrası fiziksel imha ile ortadan kaldırılması.",
            "Anonimleştirme: Verinin başka verilerle eşleştirilse dahi kimliği belirli bir kişiyle ilişkilendirilemeyecek hale getirilmesi.",
        ),
        P(
            "Arızalı veya kullanım ömrünü dolduran diskler veri merkezinden çıkarılmadan önce kriptografik olarak "
            "silinir ve lisanslı imha firmasına tutanakla teslim edilir. Kağıt belgeler genel merkezdeki kilitli "
            "imha kutularında toplanır."
        ),
        H1("5. Periyodik İmha"),
        P(
            "Saklama süresi dolan kişisel veriler, altı ayda bir yapılan periyodik imha işlemleriyle silinir. "
            "Periyodik imha her yıl haziran ve aralık aylarında gerçekleştirilir. Her imha işlemi bir tutanakla "
            "kayıt altına alınır; imha tutanakları 3 yıl süreyle saklanır. 2025 Aralık dönemindeki imha işleminde "
            "4.812 aday kaydı ve 27 adet emekliye ayrılmış disk imha edilmiştir."
        ),
        P(
            "İlgili kişinin silme talebi üzerine, talebe konu verilerin işlenme şartlarının tamamı ortadan kalkmışsa "
            "veriler talep tarihinden itibaren en geç 30 gün içinde silinir ve ilgili kişiye bilgi verilir."
        ),
        H1("6. Veri İhlali Bildirimi"),
        P(
            "Kişisel verilerin kanuni olmayan yollarla başkaları tarafından elde edildiğinin öğrenilmesi halinde, "
            "durum öğrenme anından itibaren en geç 72 saat içinde Kişisel Verileri Koruma Kurulu'na bildirilir. "
            "Etkilenen ilgili kişilere ise en kısa sürede doğrudan veya uygun yöntemlerle bilgi verilir. Olay "
            "müdahalesini BT Müdürü Emre Kaya, hukuki değerlendirmeyi ve Kurul bildirimini Hukuk ve Uyum Müdürü "
            "Elif Aydın yürütür."
        ),
        H1("7. Görev ve Sorumluluklar"),
        T(
            ("Unvan", "Sorumluluk"),
            (
                ("Hukuk ve Uyum Müdürü", "Politikanın sahibi; yıllık gözden geçirme"),
                ("Uyum Uzmanı", "İrtibat kişisi; imha tutanakları"),
                ("BT Müdürü", "Teknik silme ve yedek döngüsü"),
                ("İK Müdürü", "Aday ve personel verileri"),
                ("Departman yöneticileri", "Kendi veri envanterlerinin güncelliği"),
            ),
            widths=(2.0, 4.0),
        ),
        H1("8. Gözden Geçirme"),
        P(
            "Politika en az yılda bir kez, ayrıca mevzuat değişikliklerinde Hukuk ve Uyum Müdürlüğü tarafından "
            "gözden geçirilir. Sürüm 2.1'de destek talepleri ve ticari ileti onayları için saklama süreleri "
            "tabloya eklenmiş, kiracı verileri için 90 günlük silme süresi Veri İşleme Sözleşmesi ile uyumlu "
            "hale getirilmiştir."
        ),
    ),
)

DPA = Doc(
    path="hukuk-uyum/Data_Processing_Agreement_Template_v2026.docx",
    title="Data Processing Agreement (Template)",
    subtitle="Annex to the NebulaCRM Master Subscription Agreement",
    lang="en",
    date=D(2026, 7, 1),
    doc_no="HUK-SOZ-011",
    meta=(
        ("Version", "2026.1"),
        ("Owner", "Elif Aydın, Legal & Compliance Manager"),
        ("Drafted by", "Naz Kurt, Legal Counsel"),
        ("Effective", "1 July 2026"),
        ("Replaces", "DPA template 2025.2"),
    ),
    blocks=(
        H1("1. Definitions"),
        P(
            "In this Data Processing Agreement (DPA), Customer means the entity that has subscribed to NebulaCRM "
            "under the Master Subscription Agreement (MSA); Nebula means Nebula Teknoloji A.Ş. and, where the "
            "Customer is served from Germany, its affiliate Nebula Technology GmbH; Customer Data means any "
            "personal data uploaded to or generated in the Customer's NebulaCRM tenant; Sub-processor means any "
            "third party engaged by Nebula that processes Customer Data. Terms not defined here have the meaning "
            "given in the Turkish Personal Data Protection Law No. 6698 (KVKK) and, for customers established in "
            "the European Economic Area, the GDPR."
        ),
        H1("2. Roles and Scope"),
        P(
            "The Customer is the data controller and Nebula is the data processor. Nebula processes Customer Data "
            "only on the Customer's documented instructions, which consist of this DPA, the MSA and the "
            "configuration choices the Customer makes in the product. Annex 1 describes the subject matter, "
            "categories of data subjects and categories of personal data."
        ),
        H1("3. Processor Obligations"),
        P(
            "Nebula ensures that every person authorised to process Customer Data is bound by confidentiality, "
            "receives annual data protection training and has access only to the extent needed for their role. "
            "Nebula will assist the Customer with data subject requests and will forward any request it receives "
            "directly within 5 business days."
        ),
        H1("4. Sub-processors"),
        P(
            "The Customer grants general authorisation for Nebula to engage the Sub-processors listed in the "
            "public register at trust.nebulacrm.example/subprocessors. Nebula will notify the Customer at least "
            "30 days before adding or replacing a Sub-processor. The Customer may object on reasonable data "
            "protection grounds within 14 days of the notice; if the parties cannot resolve the objection, the "
            "Customer may terminate the affected service without penalty and receive a pro-rata refund."
        ),
        H1("5. Security"),
        P(
            "Nebula maintains the technical and organisational measures described in Annex 2, which are aligned "
            "with its ISO/IEC 27001:2022 certified information security management system. Nebula may update the "
            "measures provided the overall level of protection is not reduced."
        ),
        H1("6. Personal Data Breach"),
        P(
            "Nebula will notify the Customer without undue delay and in any event within 48 hours after becoming "
            "aware of a personal data breach affecting Customer Data. The notice will describe the nature of the "
            "breach, the categories and approximate number of data subjects and records concerned, the likely "
            "consequences and the measures taken or proposed. Where information is not yet available, Nebula "
            "will provide it in phases. Notifying supervisory authorities and data subjects remains the "
            "Customer's responsibility as controller, and Nebula will provide reasonable assistance."
        ),
        H1("7. Audits"),
        P(
            "The Customer may audit Nebula's compliance with this DPA once in any 12-month period, on at least "
            "30 days' written notice, during normal business hours and through an independent auditor bound by "
            "confidentiality. Nebula's current ISO/IEC 27001 certificate and surveillance audit summary will be "
            "accepted in place of an on-site audit unless a regulator requires otherwise or a breach has "
            "occurred. Audit costs are borne by the Customer unless the audit reveals a material breach of this DPA."
        ),
        H1("8. Data Location and Transfers"),
        P(
            "Customer Data is stored in Türkiye: production in the İstanbul data centre IST-1 and disaster recovery "
            "replicas in the Ankara site ANK-DR1. Customers who select EU hosting are served from the FRA-1 region "
            "in Frankfurt, Germany, available since 1 July 2026; for these customers Customer Data, including "
            "backups, is stored only in the EU. Nebula will not transfer Customer Data outside the selected "
            "region except to the Sub-processors and locations shown in the register."
        ),
        H1("9. Return and Deletion"),
        P(
            "During the 30 days following termination the Customer may export its Customer Data using the "
            "self-service export tool. Nebula permanently deletes Customer Data from production systems 90 days "
            "after termination of the MSA. Residual copies in backups are overwritten within a further 35 days "
            "by the normal backup cycle. Nebula will confirm deletion in writing on request."
        ),
        H1("10. Liability"),
        P(
            "Each party's liability under this DPA is subject to the limitations and exclusions of liability in "
            "the MSA. Nothing in this DPA limits liability that cannot be limited under applicable law."
        ),
        H1("11. Term and Governing Law"),
        P(
            "This DPA remains in force for as long as Nebula processes Customer Data. It is governed by Turkish law "
            "and disputes are subject to the exclusive jurisdiction of the İstanbul (Çağlayan) courts. For "
            "customers contracting with Nebula Technology GmbH, German law applies and the courts of Berlin have "
            "jurisdiction."
        ),
        H1("Annex 1 — Description of Processing"),
        T(
            ("Item", "Description"),
            (
                ("Subject matter", "Provision of NebulaCRM and related support"),
                ("Duration", "Term of the MSA plus 90 days"),
                ("Data subjects", "Customer's contacts, leads, employees and users"),
                (
                    "Personal data",
                    "Names, business contact details, communication history, notes, call logs",
                ),
                (
                    "Special categories",
                    "Not intended; Customer must not upload them unless agreed in writing",
                ),
                (
                    "Processing operations",
                    "Storage, search, analytics, AI-assisted summaries (Nebula Assist)",
                ),
            ),
        ),
        H1("Annex 2 — Technical and Organisational Measures"),
        T(
            ("Area", "Measure"),
            (
                ("Encryption", "AES-256 at rest; TLS 1.2 or higher in transit"),
                ("Access control", "MFA for all staff; FIDO2 keys for administrators"),
                (
                    "Tenant isolation",
                    "tenant_id with row-level security; dedicated clusters for Kurumsal Plus",
                ),
                ("Backups", "Continuous WAL archiving; RPO 15 minutes; 35-day retention"),
                ("Logging", "Access logs retained for 2 years"),
                (
                    "Testing",
                    "Annual external penetration test; disaster recovery test twice a year",
                ),
            ),
        ),
    ),
)

SUBPROCESSORS = Doc(
    path="hukuk-uyum/Subprocessor_Register_2026.xlsx",
    title="Sub-processor Register 2026",
    lang="en",
    date=D(2026, 7, 1),
    sheets=(
        Sheet(
            name="Sub-processors",
            title="NebulaCRM Sub-processor Register — version of 1 July 2026",
            header=(
                "No",
                "Sub-processor",
                "Service Provided",
                "Processing Location",
                "Data Categories",
                "Applies To",
                "Processing Since",
                "Safeguard",
            ),
            rows=(
                (
                    1,
                    "Kumulus Bulut Hizmetleri A.Ş.",
                    "Colocation for primary data centre IST-1",
                    "Türkiye (İstanbul)",
                    "All Customer Data (encrypted at rest)",
                    "All Türkiye-hosted tenants",
                    "01.03.2019",
                    "Contract + ISO/IEC 27001",
                ),
                (
                    2,
                    "Anka Veri Merkezleri A.Ş.",
                    "Disaster recovery site ANK-DR1",
                    "Türkiye (Ankara)",
                    "Replicas and backups of Customer Data",
                    "All Türkiye-hosted tenants",
                    "01.09.2019",
                    "Contract + ISO/IEC 27001",
                ),
                (
                    3,
                    "Rheinwerk Hosting GmbH",
                    "Hosting for EU region FRA-1",
                    "Germany (Frankfurt)",
                    "All Customer Data of EU-hosted tenants",
                    "Tenants with EU hosting",
                    "01.07.2026",
                    "GDPR Art. 28 contract",
                ),
                (
                    4,
                    "Terra LLM Hizmetleri A.Ş.",
                    "LLM inference for Nebula Assist",
                    "Türkiye (İstanbul)",
                    "Prompts and CRM record excerpts; zero retention; no training",
                    "Tenants using Nebula Assist",
                    "01.07.2026",
                    "Contract + no-training clause",
                ),
                (
                    5,
                    "PostaGüvercini İleti A.Ş.",
                    "Transactional e-mail delivery",
                    "Türkiye (İstanbul)",
                    "User names and e-mail addresses",
                    "All tenants",
                    "15.02.2021",
                    "Contract",
                ),
                (
                    6,
                    "Lyra Mesaj A.Ş.",
                    "SMS one-time passwords",
                    "Türkiye (İzmir)",
                    "Mobile phone numbers",
                    "Tenants using SMS OTP",
                    "01.04.2026",
                    "Contract",
                ),
                (
                    7,
                    "Nebula Technology GmbH",
                    "Affiliate: DACH sales and customer support",
                    "Germany (Berlin)",
                    "Support tickets and contact details",
                    "DACH customers",
                    "02.02.2026",
                    "Intra-group agreement",
                ),
                (
                    8,
                    "Mercan Ödeme Hizmetleri A.Ş.",
                    "Card payments for self-service Başlangıç plans",
                    "Türkiye (İstanbul)",
                    "Billing contact and tokenised card data",
                    "Başlangıç plan customers",
                    "10.01.2023",
                    "Contract + PCI DSS",
                ),
                (
                    9,
                    "Ayaz Çağrı Teknolojileri A.Ş.",
                    "Telephony for the support line",
                    "Türkiye (İzmir)",
                    "Caller numbers and call recordings",
                    "Customers calling support",
                    "01.09.2025",
                    "Contract",
                ),
                (
                    10,
                    "Kalkan Siber Güvenlik A.Ş.",
                    "24/7 security operations monitoring",
                    "Türkiye (Ankara)",
                    "Security logs incl. IP addresses and user IDs",
                    "All tenants",
                    "01.01.2024",
                    "Contract + ISO/IEC 27001",
                ),
            ),
            notes=(
                (
                    "Customers are notified at least 30 days before a sub-processor is added or replaced; "
                    "objections may be raised within 14 days of the notice (DPA clause 4)."
                ),
                "Register owner: Onur Aslan, Compliance Specialist. Public copy: trust.nebulacrm.example/subprocessors.",
            ),
            widths=(5, 30, 40, 22, 44, 28, 16, 28),
        ),
        Sheet(
            name="Change Log",
            header=("Date", "Change", "Sub-processor", "Notice Sent", "Objections Received"),
            rows=(
                ("15.02.2021", "Added", "PostaGüvercini İleti A.Ş.", "n/a (initial register)", 0),
                ("10.01.2023", "Added", "Mercan Ödeme Hizmetleri A.Ş.", "09.12.2022", 0),
                ("01.01.2024", "Added", "Kalkan Siber Güvenlik A.Ş.", "28.11.2023", 1),
                ("01.09.2025", "Added", "Ayaz Çağrı Teknolojileri A.Ş.", "30.07.2025", 0),
                ("02.02.2026", "Added", "Nebula Technology GmbH", "02.01.2026", 0),
                ("31.03.2026", "Removed", "Bora İletişim A.Ş. (SMS)", "27.02.2026", 0),
                ("01.04.2026", "Added", "Lyra Mesaj A.Ş.", "27.02.2026", 0),
                ("01.07.2026", "Added", "Rheinwerk Hosting GmbH", "29.05.2026", 0),
                ("01.07.2026", "Added", "Terra LLM Hizmetleri A.Ş.", "29.05.2026", 2),
            ),
            notes=(
                (
                    "The two objections to Terra LLM Hizmetleri A.Ş. were resolved by allowing those customers to keep "
                    "Nebula Assist disabled at tenant level."
                ),
            ),
        ),
    ),
)

ETHICS = Doc(
    path="hukuk-uyum/Etik_Kurallar_ve_Ihbar_Proseduru.md",
    title="Etik Kurallar ve İhbar Prosedürü",
    lang="tr",
    date=D(2026, 1, 5),
    doc_no="HUK-POL-001",
    meta=(
        ("Sürüm", "4.0"),
        ("Sahibi", "Elif Aydın, Hukuk ve Uyum Müdürü"),
        ("Onaylayan", "Yönetim Kurulu (17 Aralık 2025)"),
        ("Yürürlük", "1 Ocak 2026"),
    ),
    blocks=(
        H1("1. Amaç ve Kapsam"),
        P(
            "Bu belge, Nebula Teknoloji A.Ş. ve bağlı şirketi Nebula Technology GmbH çalışanlarının, yöneticilerinin "
            "ve şirket adına hareket eden danışmanların uyması gereken etik davranış ilkelerini ve etik ihlallerin "
            "bildirilmesi, incelenmesi ve sonuçlandırılmasına ilişkin prosedürü düzenler. Kurallar tüm ofislerde "
            "ve uzaktan çalışırken aynı şekilde geçerlidir."
        ),
        H1("2. Temel İlkeler"),
        UL(
            "Dürüstlük: Müşterilere, iş ortaklarına ve birbirimize karşı doğru ve eksiksiz bilgi veririz.",
            "Gizlilik: Müşteri verisini yalnızca hizmetin gerektirdiği ölçüde ve yetkimiz dahilinde kullanırız.",
            "Adil rekabet: Rakiplerle fiyat, müşteri veya bölge paylaşımı anlamına gelebilecek görüşmeler yapmayız.",
            "Saygı: Ayrımcılığa, tacize ve mobbinge hiçbir koşulda göz yummayız.",
            "Yolsuzlukla mücadele: Kamu görevlilerine veya özel sektör çalışanlarına doğrudan ya da dolaylı olarak "
            "rüşvet teklif etmeyiz; kolaylaştırma ödemeleri de yasaktır.",
        ),
        H1("3. Hediye ve Ağırlama"),
        P(
            "Çalışanlar, iş ilişkisi bulunan kişi ve kurumlardan değeri 2.000 TL'yi aşan hediye kabul edemez ve bu "
            "değeri aşan hediye veremez. Bu limit 2025 yılında 1.500 TL idi; enflasyon etkisi dikkate alınarak "
            "1 Ocak 2026'dan itibaren güncellenmiştir. Aynı kişi veya kurumdan bir takvim yılı içinde alınan "
            "hediyelerin toplam değeri 5.000 TL'yi geçemez."
        ),
        P(
            "Limit altında kalsa dahi nakit, hediye çeki veya kripto varlık niteliğindeki hediyeler kabul edilmez. "
            "Reddedilmesi iş ilişkisine zarar verecek hediyeler kabul edilip 5 iş günü içinde Hediye Kayıt Formu ile "
            "Hukuk ve Uyum Müdürlüğü'ne bildirilir; bu hediyeler yılsonunda hayır kurumlarına bağışlanır. Bir ihale "
            "veya satın alma süreci devam ederken ilgili tedarikçiden hiçbir hediye veya ağırlama kabul edilmez."
        ),
        H1("4. Çıkar Çatışması"),
        P(
            "Çalışanlar; bir tedarikçide, müşteride veya rakipte kendilerinin ya da birinci derece yakınlarının sahip "
            "olduğu %5'i aşan ortaklık paylarını, bu kurumlarda üstlendikleri görevleri ve şirket dışındaki ücretli "
            "işlerini beyan etmek zorundadır. Yıllık çıkar çatışması beyanı her yıl 31 Ocak'a kadar İK Portalı "
            "üzerinden doldurulur. Yöneticiler, doğrudan veya dolaylı raporlama ilişkisi bulunan bir yakınlarının "
            "işe alım, terfi veya ücret kararlarında yer alamaz."
        ),
        H1("5. Etik İhbar Kanalları"),
        P(
            "Etik kurallara aykırı olduğundan şüphelenilen her durum aşağıdaki kanallardan biriyle bildirilebilir. "
            "Bildirimler isimli veya anonim yapılabilir; anonim bildirimler de isimli bildirimlerle aynı özenle "
            "incelenir."
        ),
        T(
            ("Kanal", "Erişim", "Not"),
            (
                ("E-posta", "etik@nebulacrm.example", "Yalnızca Etik Kurul üyeleri erişebilir"),
                ("Telefon", "Dahili 1999", "Mesai dışında sesli mesaj bırakılabilir"),
                ("Web formu", "etik.nebulacrm.example", "Anonim bildirim için IP adresi saklanmaz"),
                (
                    "Bağımsız üye",
                    "Dr. Levent Sarıgül",
                    "Üst yönetimi ilgilendiren bildirimler için",
                ),
            ),
        ),
        H1("6. İnceleme Süreci"),
        OL(
            "Bildirim, alındığı tarihten itibaren en geç 3 iş günü içinde kayda alınır ve bildirim sahibine "
            "(iletişim bilgisi varsa) alındı bilgisi verilir.",
            "Etik Kurul, ön değerlendirmeyi 10 iş günü içinde tamamlar ve inceleme açılıp açılmayacağına karar verir.",
            "İncelemeler, bildirimin alındığı tarihten itibaren 45 gün içinde sonuçlandırılır. Karmaşık vakalarda "
            "süre, Kurul kararıyla bir defaya mahsus 30 gün uzatılabilir.",
            "Sonuç ve alınan önlemler, kişisel verilerin korunmasına dikkat edilerek bildirim sahibine iletilir.",
        ),
        P(
            "Etik Kurul; Hukuk ve Uyum Müdürü Elif Aydın'ın başkanlığında, İnsan Kaynakları Müdürü Burak Çelik ve "
            "bağımsız yönetim kurulu üyesi Dr. Levent Sarıgül'den oluşur. Kurul üyelerinden birini ilgilendiren "
            "bildirimlerde ilgili üye sürece katılmaz. CEO veya yönetim kurulu üyelerini ilgilendiren bildirimler "
            "doğrudan Denetim Komitesi Başkanı Dr. Levent Sarıgül'e iletilir."
        ),
        H1("7. Misillemenin Yasaklanması"),
        P(
            "İyi niyetle bildirimde bulunan hiçbir çalışan, bildirimi nedeniyle işten çıkarma, olumsuz performans "
            "değerlendirmesi, görev değişikliği veya benzeri bir misillemeye maruz bırakılamaz. Misilleme tespit "
            "edilirse ayrı bir disiplin süreci başlatılır. Bilerek yanlış bildirimde bulunmak da etik ihlal sayılır."
        ),
        H1("8. Eğitim ve Raporlama"),
        P(
            "Tüm çalışanlar yılda bir kez çevrimiçi etik ve yolsuzlukla mücadele eğitimini tamamlar; 2026 eğitiminin "
            "son tamamlanma tarihi 30 Nisan 2026'dır. 2025 yılında eğitim tamamlama oranı %96 olmuştur. Etik Kurul, "
            "her yıl şubat ayında Denetim Komitesi'ne yıllık rapor sunar. 2025 raporuna göre etik hattına 14 bildirim "
            "ulaşmış; bunların 9'u incelenerek kapatılmış (3'ünde ihlal tespit edilmiştir), 3'ü ön değerlendirmede "
            "kapsam dışı bulunmuş ve 2'si inceleme aşamasında 2026'ya devretmiştir."
        ),
    ),
)

DOCS = [KVKK, DPA, SUBPROCESSORS, ETHICS]
