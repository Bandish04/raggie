# SPDX-License-Identifier: Apache-2.0

"""Ürün Yönetimi: NebulaCRM v3.3 / v3.4 release notes and the Nebula Assist PRD."""

from model import H1, H2, OL, UL, D, Doc, P, T

V33 = Doc(
    path="urun-yonetimi/Surum_Notlari_NebulaCRM_v3.3.md",
    title="NebulaCRM v3.3 Sürüm Notları",
    subtitle="Genel kullanıma açılış: 12 Mayıs 2026",
    lang="tr",
    date=D(2026, 5, 12),
    doc_no="URN-SN-033",
    meta=(
        ("Sürüm", "3.3.0"),
        ("Sahibi", "Merve Doğan (Ürün Müdürü)"),
        ("Hazırlayan", "İrem Korkmaz (Ürün Sahibi)"),
        ("Önceki sürüm", "3.2.0 (10 Şubat 2026)"),
    ),
    blocks=(
        H1("Özet"),
        P(
            "NebulaCRM v3.3, 12 Mayıs 2026 tarihinde tüm müşterilere kademeli olarak açıldı. Sürümün ana "
            "teması uluslararası satış ekipleri ve büyük veri hacmiyle çalışan müşteriler: çok para "
            "birimli teklifler, e-Fatura entegrasyonu, yeni Kanban satış hunisi görünümü ve daha yüksek "
            "içe aktarma ile API limitleri bu sürümle geliyor. Geçiş kesintisiz yapıldı; müşteri tarafında "
            "herhangi bir işlem gerekmiyor."
        ),
        H1("Yeni özellikler"),
        H2("Çok para birimli teklifler"),
        P(
            "Teklifler artık TRY, EUR ve USD cinsinden hazırlanabiliyor. Kur bilgisi teklifin "
            "oluşturulduğu günün kapanış kuru ile sabitlenir ve teklif PDF'inde gösterilir. Fırsat "
            "tutarları raporlarda hesabın ana para birimine çevrilerek toplanır. Özellik tüm planlarda "
            "açıktır; Başlangıç planında en fazla iki para birimi aynı anda kullanılabilir."
        ),
        H2("e-Fatura ve e-Arşiv entegrasyonu"),
        P(
            "Kazanılan fırsattan tek tıkla e-Fatura veya e-Arşiv taslağı oluşturulabiliyor. Taslak, "
            "müşterinin anlaşmalı entegratörüne güvenli bir bağlantı üzerinden iletilir; fatura durumu "
            "(gönderildi, kabul edildi, reddedildi) fırsat kartında izlenir. Entegrasyon Profesyonel ve "
            "üzeri planlarda kullanılabilir."
        ),
        H2("Kanban satış hunisi"),
        P(
            "Fırsatlar aşama sütunlarında kart olarak görüntüleniyor ve sürükle-bırak ile aşama "
            "değiştirilebiliyor. Her sütunun üzerinde toplam tutar ve ağırlıklı tahmin gösterilir. "
            "Kanban görünümü, aynı anda en fazla 2.000 açık fırsat gösterecek şekilde optimize edildi."
        ),
        H2("Rol bazlı alan maskeleme"),
        P(
            "Yöneticiler, T.C. kimlik numarası ve telefon gibi kişisel veri içeren alanları belirli roller "
            "için maskeleyebiliyor. Maskelenen alan listede ve dışa aktarımlarda yıldızla gösterilir. "
            "Özellik, KVKK uyum denetimlerinde en sık talep edilen kontrollerden biriydi."
        ),
        H1("Limit değişiklikleri"),
        T(
            ("Limit", "v3.2", "v3.3"),
            (
                ("Toplu içe aktarma (dosya başına)", "10.000 satır", "50.000 satır"),
                ("Profesyonel plan API hız limiti", "Dakikada 200 istek", "Dakikada 300 istek"),
                ("Kanban görünümünde açık fırsat", "Yok", "2.000"),
                ("Teklif başına ürün satırı", "100", "250"),
            ),
        ),
        P(
            "Toplu içe aktarma limiti 10.000 satırdan 50.000 satıra çıkarıldı. Profesyonel planda API hız "
            "limiti dakikada 200'den 300 isteğe yükseltildi; diğer planların limitleri değişmedi. Güncel "
            "limitlerin tamamı NebulaCRM API v3 Referansı'nda yer alır."
        ),
        H1("İyileştirmeler"),
        UL(
            "Takvim senkronizasyonu artık 5 dakika yerine 2 dakikada bir çalışıyor.",
            "Gelişmiş arama, Türkçe karakterlerden bağımsız eşleşme yapıyor (ör. 'Gunes' araması "
            "'Güneş' kaydını buluyor).",
            "Kişi kartında son 90 günün etkinlik zaman çizelgesi tek ekranda gösteriliyor.",
            "Rapor oluşturucuya yüzde değişim ve çeyrek karşılaştırma sütunları eklendi.",
            "Yönetici panelindeki denetim kaydı 12 aylık geçmişi filtreleyebiliyor.",
        ),
        H1("Giderilen hatalar"),
        UL(
            "NCRM-4812: Aynı anda iki kullanıcı tarafından düzenlenen fırsatta son kaydedilen değer "
            "uyarı vermeden ötekinin üzerine yazılıyordu.",
            "NCRM-4877: Hafta başlangıcı pazartesi olan hesaplarda haftalık raporlar bir gün kayık "
            "hesaplanıyordu.",
            "NCRM-4903: Mobil uygulamada uzun şirket adları kart görünümünde kesiliyordu.",
            "NCRM-4951: İçe aktarmada ondalık ayırıcısı virgül olan CSV dosyaları yanlış okunuyordu.",
        ),
        H1("Bilinen sorunlar"),
        UL(
            "200.000 satırın üzerindeki raporların dışa aktarımı zaman aşımına uğrayabilir. Geçici "
            "çözüm olarak raporu tarih aralığına bölerek dışa aktarın; kalıcı çözüm sonraki sürümler "
            "için planlanmıştır.",
            "Kanban görünümünde 2.000'den fazla açık fırsatı olan hesaplarda liste görünümü varsayılan "
            "olarak açılır.",
        ),
        H1("Yöneticiler için notlar"),
        UL(
            "e-Fatura entegrasyonu varsayılan olarak kapalıdır; Ayarlar > Entegrasyonlar > e-Fatura "
            "ekranından entegratör bilgileri girilerek etkinleştirilir.",
            "Alan maskeleme kuralları yalnızca Hesap Yöneticisi rolündeki kullanıcılar tarafından "
            "tanımlanabilir ve her değişiklik denetim kaydına yazılır.",
            "Yeni içe aktarma limiti, 50.000 satırın üzerindeki dosyaların otomatik olarak 50.000 "
            "satırlık parçalara bölünmesini gerektirir; içe aktarma sihirbazı bunu kullanıcıya önerir.",
            "Mevcut entegrasyonlar dakikada 300 isteğe çıkan Profesyonel limitinden otomatik olarak "
            "yararlanır; anahtar yenilemeye gerek yoktur.",
        ),
        H1("Kullanımdan kaldırma duyuruları"),
        P(
            "API v2 uç noktaları 31 Mart 2027 tarihinde kapatılacaktır. API v2 kullanan müşterilerin bu "
            "tarihe kadar v3'e geçmesi gerekir. Geçiş rehberi geliştirici portalında yayımlandı; Kurumsal "
            "ve Kurumsal Plus müşterileri için Teknik Hesap Yöneticileri geçiş planlaması desteği verir."
        ),
        H1("Sonraki sürüm"),
        P(
            "v3.4 sürümünün Eylül 2026'da yayımlanması planlanıyor. Nebula Assist yapay zekâ asistanının "
            "beta programı 1 Temmuz 2026'da seçili pilot müşterilerle başlayacak."
        ),
    ),
)

V34 = Doc(
    path="urun-yonetimi/Release_Notes_NebulaCRM_v3.4.md",
    title="NebulaCRM v3.4 Release Notes",
    subtitle="General availability: 15 September 2026",
    lang="en",
    date=D(2026, 9, 15),
    doc_no="URN-RN-034",
    meta=(
        ("Version", "3.4.0"),
        ("Owner", "Merve Doğan (Product Manager)"),
        ("Prepared by", "İrem Korkmaz (Product Owner)"),
        ("Previous release", "3.3.0 (12 May 2026)"),
    ),
    blocks=(
        H1("Highlights"),
        P(
            "NebulaCRM v3.4 became generally available on 15 September 2026. This release makes Nebula "
            "Assist, our AI assistant, generally available, rebuilds report export from the ground up, "
            "adds a native telephony connector and gives customers in the DACH region a self-service path "
            "to the FRA-1 EU region. The rollout was completed for all tenants by 18 September 2026 "
            "without downtime."
        ),
        H1("Nebula Assist is generally available"),
        P(
            "Nebula Assist answers questions about accounts, deals and activities, summarises calls and "
            "drafts follow-up e-mails. Every answer cites the CRM records it was built from, and the "
            "assistant only sees records the user is already allowed to open. Customer data is never used "
            "to train models."
        ),
        UL(
            "Included in Kurumsal (500 requests per user per month) and Kurumsal Plus (1,500 requests "
            "per user per month).",
            "Available for Profesyonel as an add-on at TRY 240 per user per month.",
            "Languages: Turkish, English and German.",
            "Administrators can switch the assistant off per tenant or per role in Settings > Nebula Assist.",
        ),
        P(
            "Assist moves out of the beta that started on 1 July 2026 with 40 pilot customers. Usage "
            "during the beta is not counted against the new monthly quotas."
        ),
        H1("Report export, rebuilt"),
        P(
            "Report export now runs on a streaming engine instead of building the whole file in memory. "
            "In our benchmark a report with 1 million rows exports to CSV in under 90 seconds; in v3.3, "
            "exports above 200,000 rows could time out. XLSX exports are capped at the format's own "
            "limit of 1,048,576 rows per sheet. Large exports continue in the background and the user is "
            "notified when the file is ready to download; download links expire after 7 days."
        ),
        H1("Native CTI telephony connector"),
        P(
            "NebulaCRM v3.4 introduces a native CTI telephony connector. Calls placed or received through "
            "a SIP-based call-centre system are logged automatically on the matching contact, with "
            "duration, direction and outcome. Click-to-call works from contact and deal cards. The "
            "connector is available on Profesyonel and above and is configured by an administrator in "
            "Settings > Integrations > Telephony."
        ),
        H1("EU data residency: FRA-1 tenant migration"),
        P(
            "The FRA-1 region in Frankfurt opened for new DACH customers on 1 July 2026. With v3.4, "
            "existing tenants can request migration to FRA-1 from the admin console. Migrations are "
            "scheduled with the customer's Technical Account Manager or the support team; the tenant is "
            "read-only for at most 30 minutes during the final cut-over. Data is copied, verified and "
            "then deleted from the source region within 14 days."
        ),
        H1("Limits"),
        T(
            ("Limit", "v3.3", "v3.4"),
            (
                ("Bulk import (per file)", "50,000 rows", "100,000 rows"),
                ("CSV report export", "about 200,000 rows", "1,000,000+ rows"),
                ("Nebula Assist requests (Kurumsal)", "Beta only", "500 per user per month"),
                ("Nebula Assist requests (Kurumsal Plus)", "Beta only", "1,500 per user per month"),
            ),
        ),
        P(
            "Bulk import now accepts up to 100,000 rows per file, up from 50,000 rows in v3.3. API rate "
            "limits are unchanged; see the NebulaCRM API v3 Reference."
        ),
        H1("Notes for administrators"),
        UL(
            "Nebula Assist is enabled by default for Kurumsal and Kurumsal Plus tenants that took part "
            "in the beta; all other eligible tenants must switch it on in Settings > Nebula Assist.",
            "Usage per user and per team is shown in Admin > Usage > Nebula Assist and can be exported.",
            "The telephony connector needs the call-centre system's SIP domain and an API credential; "
            "inbound calls from numbers that match no contact are logged as unassigned activities.",
            "FRA-1 migration requests are reviewed within 5 business days; a migration cannot be "
            "scheduled during the 15 December – 5 January release freeze.",
        ),
        H1("Mobile"),
        UL(
            "Offline mode: contacts, deals and notes from the last 30 days are available without a "
            "connection; changes sync automatically when the device is back online.",
            "Call logging from the mobile app uses the new CTI connector when it is enabled.",
            "Minimum supported mobile OS versions are now the two most recent major releases.",
        ),
        H1("Fixed issues"),
        UL(
            "NCRM-5120: Report exports above 200,000 rows timed out (replaced by the streaming engine).",
            "NCRM-5177: Mobile sync could duplicate notes created while switching networks.",
            "NCRM-5203: Webhook deliveries for deal.stage_changed were sent twice after a manual retry.",
            "NCRM-5246: Multi-currency quotes rounded EUR totals incorrectly when a line discount was applied.",
        ),
        H1("Deprecations and upcoming changes"),
        UL(
            "API v2 will be switched off on 31 March 2027. Customers still calling v2 endpoints receive "
            "a Deprecation response header and a monthly reminder e-mail.",
            "The legacy report export endpoint will be removed in v3.5; use the asynchronous export API.",
            "NebulaCRM v3.5 is planned for 8 December 2026.",
        ),
    ),
)

PRD = Doc(
    path="urun-yonetimi/PRD_Nebula_Assist.docx",
    title="Ürün Gereksinim Dokümanı: Nebula Assist",
    subtitle="NebulaCRM için kaynak gösteren yapay zekâ asistanı",
    lang="tr",
    date=D(2026, 4, 10),
    doc_no="URN-PRD-018",
    meta=(
        ("Sürüm", "1.4"),
        ("Sahibi", "İrem Korkmaz (Ürün Sahibi)"),
        ("Onaylayan", "Merve Doğan (Ürün Müdürü)"),
        (
            "Katkıda bulunanlar",
            "Gizem Aksoy (Veri Bilimci), Yusuf Eren (UX Tasarımcısı), Okan Yıldız (Kıdemli Yazılım Mühendisi)",
        ),
        ("Durum", "Onaylandı"),
    ),
    blocks=(
        H1("1. Problem"),
        P(
            "Satış temsilcilerimizle yaptığımız 24 görüşme ve 312 yanıtlı kullanıcı anketi, temsilcilerin "
            "haftada ortalama 5,5 saatini CRM'e veri girmeye ve kayıt aramaya harcadığını gösterdi. "
            "Görüşme notları çoğu zaman gün sonunda, eksik ve dağınık giriliyor; yöneticiler fırsat "
            "durumunu öğrenmek için kayıtları tek tek açmak zorunda kalıyor. Rakip ürünlerdeki genel "
            "amaçlı sohbet asistanları ise kaynak göstermediği için kurumsal müşterilerimizde güven "
            "sorunu yaratıyor."
        ),
        H1("2. Hedefler"),
        UL(
            "Bir müşteri görüşmesinin CRM'e kaydedilme süresini %40 azaltmak.",
            "Yöneticilerin fırsat ve hesap durumunu doğal dilde sorup kaynaklı yanıt alabilmesini sağlamak.",
            "Kurumsal segmentte yapay zekâ özelliklerini güvenle kullanılabilir kılmak: kaynak gösterimi, "
            "yetkiye saygı ve veri izolasyonu.",
        ),
        H2("Kapsam dışı"),
        UL(
            "Sesli asistan ve telefon görüşmesinin canlı transkripsiyonu.",
            "Kullanıcı onayı olmadan e-posta gönderme; Assist yalnızca taslak üretir.",
            "Kayıtların asistan tarafından toplu olarak güncellenmesi.",
        ),
        H1("3. Başarı metrikleri"),
        T(
            ("Metrik", "Hedef", "Ölçüm"),
            (
                (
                    "Haftalık aktif kullanım",
                    "GA'dan 90 gün sonra lisanslı koltukların %35'i",
                    "Ürün analitiği",
                ),
                ("Önerilen özetlerin kabul oranı", "En az %70", "Kullanıcı düzenleme oranı"),
                ("Kaynak gösterilen yanıt oranı", "%100", "Otomatik kontrol"),
                ("Yanıt gecikmesi", "p95 4 saniyenin altında", "Sunucu metrikleri"),
                (
                    "Halüsinasyon oranı",
                    "Değerlendirme setinde en fazla %2",
                    "Haftalık otomatik değerlendirme",
                ),
                ("Assist memnuniyeti", "5 üzerinden en az 4,2", "Uygulama içi anket"),
            ),
        ),
        H1("4. Fonksiyonel gereksinimler"),
        T(
            ("ID", "Gereksinim", "Öncelik"),
            (
                (
                    "AS-01",
                    "Her yanıt, dayandığı CRM kayıtlarına bağlantılı kaynak göstermelidir.",
                    "Zorunlu",
                ),
                (
                    "AS-02",
                    "Görüşme notlarından otomatik özet ve sonraki adım önerisi üretilmelidir.",
                    "Zorunlu",
                ),
                (
                    "AS-03",
                    "Fırsat bağlamına göre takip e-postası taslağı oluşturulmalıdır.",
                    "Zorunlu",
                ),
                (
                    "AS-04",
                    "Uzun süredir hareketsiz fırsatlar için risk uyarısı verilmelidir.",
                    "Önemli",
                ),
                (
                    "AS-05",
                    "Kullanıcı yalnızca erişim yetkisi olan kayıtlar hakkında yanıt almalıdır.",
                    "Zorunlu",
                ),
                (
                    "AS-06",
                    "Türkçe, İngilizce ve Almanca soru ve yanıt desteklenmelidir.",
                    "Zorunlu",
                ),
                (
                    "AS-07",
                    "Aylık istek kotası Kurumsal planda kullanıcı başına 500, Kurumsal Plus planda 1.500 olmalıdır.",
                    "Zorunlu",
                ),
                ("AS-08", "Müşteri verisi model eğitiminde kullanılmamalıdır.", "Zorunlu"),
                (
                    "AS-09",
                    "Yönetici panelinde kullanıcı ve ekip bazında kullanım raporu bulunmalıdır.",
                    "Önemli",
                ),
                (
                    "AS-10",
                    "Assist, kiracı ve rol bazında yönetici tarafından kapatılabilmelidir.",
                    "Zorunlu",
                ),
            ),
        ),
        H1("5. Fonksiyonel olmayan gereksinimler"),
        UL(
            "Yanıt gecikmesi p95 değeri 4 saniyenin altında olmalıdır; ilk token 1,5 saniye içinde "
            "akmaya başlamalıdır.",
            "Çıkarım hizmeti Türkiye'de barındırılmalıdır; AB içinde barındırılan bir uç nokta devreye "
            "alınana kadar FRA-1 bölgesindeki kiracılarda Nebula Assist varsayılan olarak kapalı gelir. "
            "Kullanılan sağlayıcılar alt işleyen kaydında listelenir.",
            "İstek ve yanıt içerikleri 30 gün boyunca yalnızca kalite incelemesi amacıyla, kiracı bazında "
            "şifreli olarak tutulmalıdır.",
            "İstek başına çıkarım maliyeti hedefi 0,45 TL'nin altındadır.",
            "Hizmet dışı kalma durumunda NebulaCRM'in geri kalanı etkilenmemeli; Assist paneli "
            "'şu anda kullanılamıyor' mesajı göstermelidir.",
        ),
        H1("6. Kullanıcı deneyimi"),
        P(
            "Assist, kayıt kartlarının sağında açılan bir panel olarak tasarlandı. Yusuf Eren'in yürüttüğü "
            "kullanılabilirlik testlerinde 12 katılımcının 11'i ilk denemede kaynak bağlantısını bularak "
            "ilgili kayda geçebildi. Kaynaklar yanıtın altında numaralı çipler olarak gösterilir; çipin "
            "üzerine gelindiğinde kaydın adı ve son güncellenme tarihi görünür. Yanıtın beğenilmesi veya "
            "beğenilmemesi tek tıkla geri bildirim olarak kaydedilir."
        ),
        H1("7. Yayın planı"),
        OL(
            "İç pilot: Mayıs 2026, Satış ve Müşteri Başarı ekiplerinden 25 kullanıcı.",
            "Beta: 1 Temmuz 2026, 40 pilot müşteri; beta süresince kota uygulanmaz.",
            "Genel kullanım (GA): v3.4 sürümü ile 15 Eylül 2026.",
            "GA sonrası 90. gün: başarı metriklerinin ilk resmi değerlendirmesi.",
        ),
        P(
            "Fiyatlandırma: Assist, Kurumsal ve Kurumsal Plus planlarına dahildir; Profesyonel plan için "
            "ek modül olarak sunulur. Ek modül fiyatı 2026 Fiyat Listesi'nde yer alır."
        ),
        H1("8. Riskler ve azaltımlar"),
        T(
            ("Risk", "Etki", "Azaltım"),
            (
                (
                    "Yanlış veya uydurma yanıt",
                    "Yüksek",
                    "Zorunlu kaynak gösterimi ve haftalık değerlendirme seti",
                ),
                (
                    "Yetkisiz kayda erişim",
                    "Yüksek",
                    "Sorgu anında kullanıcının yetki filtresinin uygulanması",
                ),
                (
                    "Çıkarım maliyetinin aşılması",
                    "Orta",
                    "Kota, önbellek ve istek başına maliyet takibi",
                ),
                ("Düşük benimseme", "Orta", "Kayıt kartına gömülü öneriler ve eğitim videoları"),
            ),
        ),
        H1("9. Açık sorular"),
        UL(
            "Profesyonel plan ek modülünde kota Kurumsal ile aynı mı olmalı? (Karar sahibi: Merve Doğan)",
            "Almanca yanıt kalitesi için DACH pilot müşterilerinden ayrı değerlendirme seti gerekli mi? "
            "(Karar sahibi: Gizem Aksoy)",
        ),
    ),
)

DOCS = [V33, V34, PRD]
