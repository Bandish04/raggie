# NebulaCRM v3.3 Sürüm Notları

Genel kullanıma açılış: 12 Mayıs 2026

- Doküman No: URN-SN-033
- Sürüm: 3.3.0
- Sahibi: Merve Doğan (Ürün Müdürü)
- Hazırlayan: İrem Korkmaz (Ürün Sahibi)
- Önceki sürüm: 3.2.0 (10 Şubat 2026)
- Yayın Tarihi: 12.05.2026
- Gizlilik: Şirket İçi

## Özet

NebulaCRM v3.3, 12 Mayıs 2026 tarihinde tüm müşterilere kademeli olarak açıldı. Sürümün ana teması uluslararası satış ekipleri ve büyük veri hacmiyle çalışan müşteriler: çok para birimli teklifler, e-Fatura entegrasyonu, yeni Kanban satış hunisi görünümü ve daha yüksek içe aktarma ile API limitleri bu sürümle geliyor. Geçiş kesintisiz yapıldı; müşteri tarafında herhangi bir işlem gerekmiyor.

## Yeni özellikler

### Çok para birimli teklifler

Teklifler artık TRY, EUR ve USD cinsinden hazırlanabiliyor. Kur bilgisi teklifin oluşturulduğu günün kapanış kuru ile sabitlenir ve teklif PDF'inde gösterilir. Fırsat tutarları raporlarda hesabın ana para birimine çevrilerek toplanır. Özellik tüm planlarda açıktır; Başlangıç planında en fazla iki para birimi aynı anda kullanılabilir.

### e-Fatura ve e-Arşiv entegrasyonu

Kazanılan fırsattan tek tıkla e-Fatura veya e-Arşiv taslağı oluşturulabiliyor. Taslak, müşterinin anlaşmalı entegratörüne güvenli bir bağlantı üzerinden iletilir; fatura durumu (gönderildi, kabul edildi, reddedildi) fırsat kartında izlenir. Entegrasyon Profesyonel ve üzeri planlarda kullanılabilir.

### Kanban satış hunisi

Fırsatlar aşama sütunlarında kart olarak görüntüleniyor ve sürükle-bırak ile aşama değiştirilebiliyor. Her sütunun üzerinde toplam tutar ve ağırlıklı tahmin gösterilir. Kanban görünümü, aynı anda en fazla 2.000 açık fırsat gösterecek şekilde optimize edildi.

### Rol bazlı alan maskeleme

Yöneticiler, T.C. kimlik numarası ve telefon gibi kişisel veri içeren alanları belirli roller için maskeleyebiliyor. Maskelenen alan listede ve dışa aktarımlarda yıldızla gösterilir. Özellik, KVKK uyum denetimlerinde en sık talep edilen kontrollerden biriydi.

## Limit değişiklikleri

| Limit | v3.2 | v3.3 |
| --- | --- | --- |
| Toplu içe aktarma (dosya başına) | 10.000 satır | 50.000 satır |
| Profesyonel plan API hız limiti | Dakikada 200 istek | Dakikada 300 istek |
| Kanban görünümünde açık fırsat | Yok | 2.000 |
| Teklif başına ürün satırı | 100 | 250 |

Toplu içe aktarma limiti 10.000 satırdan 50.000 satıra çıkarıldı. Profesyonel planda API hız limiti dakikada 200'den 300 isteğe yükseltildi; diğer planların limitleri değişmedi. Güncel limitlerin tamamı NebulaCRM API v3 Referansı'nda yer alır.

## İyileştirmeler

- Takvim senkronizasyonu artık 5 dakika yerine 2 dakikada bir çalışıyor.
- Gelişmiş arama, Türkçe karakterlerden bağımsız eşleşme yapıyor (ör. 'Gunes' araması 'Güneş' kaydını buluyor).
- Kişi kartında son 90 günün etkinlik zaman çizelgesi tek ekranda gösteriliyor.
- Rapor oluşturucuya yüzde değişim ve çeyrek karşılaştırma sütunları eklendi.
- Yönetici panelindeki denetim kaydı 12 aylık geçmişi filtreleyebiliyor.

## Giderilen hatalar

- NCRM-4812: Aynı anda iki kullanıcı tarafından düzenlenen fırsatta son kaydedilen değer uyarı vermeden ötekinin üzerine yazılıyordu.
- NCRM-4877: Hafta başlangıcı pazartesi olan hesaplarda haftalık raporlar bir gün kayık hesaplanıyordu.
- NCRM-4903: Mobil uygulamada uzun şirket adları kart görünümünde kesiliyordu.
- NCRM-4951: İçe aktarmada ondalık ayırıcısı virgül olan CSV dosyaları yanlış okunuyordu.

## Bilinen sorunlar

- 200.000 satırın üzerindeki raporların dışa aktarımı zaman aşımına uğrayabilir. Geçici çözüm olarak raporu tarih aralığına bölerek dışa aktarın; kalıcı çözüm sonraki sürümler için planlanmıştır.
- Kanban görünümünde 2.000'den fazla açık fırsatı olan hesaplarda liste görünümü varsayılan olarak açılır.

## Yöneticiler için notlar

- e-Fatura entegrasyonu varsayılan olarak kapalıdır; Ayarlar > Entegrasyonlar > e-Fatura ekranından entegratör bilgileri girilerek etkinleştirilir.
- Alan maskeleme kuralları yalnızca Hesap Yöneticisi rolündeki kullanıcılar tarafından tanımlanabilir ve her değişiklik denetim kaydına yazılır.
- Yeni içe aktarma limiti, 50.000 satırın üzerindeki dosyaların otomatik olarak 50.000 satırlık parçalara bölünmesini gerektirir; içe aktarma sihirbazı bunu kullanıcıya önerir.
- Mevcut entegrasyonlar dakikada 300 isteğe çıkan Profesyonel limitinden otomatik olarak yararlanır; anahtar yenilemeye gerek yoktur.

## Kullanımdan kaldırma duyuruları

API v2 uç noktaları 31 Mart 2027 tarihinde kapatılacaktır. API v2 kullanan müşterilerin bu tarihe kadar v3'e geçmesi gerekir. Geçiş rehberi geliştirici portalında yayımlandı; Kurumsal ve Kurumsal Plus müşterileri için Teknik Hesap Yöneticileri geçiş planlaması desteği verir.

## Sonraki sürüm

v3.4 sürümünün Eylül 2026'da yayımlanması planlanıyor. Nebula Assist yapay zekâ asistanının beta programı 1 Temmuz 2026'da seçili pilot müşterilerle başlayacak.
