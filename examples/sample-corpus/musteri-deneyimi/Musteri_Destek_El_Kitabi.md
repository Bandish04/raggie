# Müşteri Destek El Kitabı

Destek ekibi için kanallar, önceliklendirme, kademeler ve eskalasyon kuralları

- Doküman No: MD-REH-001
- Sürüm: 5.0
- Sahibi: Can Öztürk (Müşteri Deneyimi Müdürü)
- Hazırlayan: Derya Kılıç (Destek Uzmanı)
- Yürürlük: 02.03.2026
- Yayın Tarihi: 02.03.2026
- Gizlilik: Şirket İçi

## 1. Amaç ve kapsam

Bu el kitabı, NebulaCRM müşterilerinden gelen destek taleplerinin nasıl karşılandığını, önceliklendirildiğini ve gerektiğinde nasıl eskale edildiğini tanımlar. İzmir Müşteri Destek Merkezi'ndeki L1 ekibi, İstanbul'daki L2 ürün uzmanları ve Ar-Ge nöbet ekibi bu kurallara uyar. Plan bazındaki süre taahhütleri bu dokümanda tekrar edilmez; güncel değerler için Destek SLA Matrisi 2026 dosyası esas alınır.

El kitabı her yıl mart ayında gözden geçirilir. Sürüm 5.0, İzmir merkezinin ilk tam yılı sonunda toplanan geri bildirimlerle hazırlanmıştır.

## 2. Destek kanalları

- E-posta: destek@nebulacrm.example adresine gelen her ileti otomatik olarak destek platformunda bir talep açar. Tüm planlar için geçerlidir.
- Telefon: Profesyonel, Kurumsal ve Kurumsal Plus müşterileri için. Numara müşteri portalında, hesap yöneticisinin imza bloğunda ve sözleşme ekinde yer alır.
- Uygulama içi sohbet: Kurumsal ve Kurumsal Plus planlarında, NebulaCRM arayüzünün sağ alt köşesindeki yardım düğmesinden açılır. Sohbet 10 dakikadan uzun sürerse talebe dönüştürülür.
- Özel kanal: Kurumsal Plus müşterileri için Teknik Hesap Yöneticisi (TAM) ile ortak mesajlaşma kanalı. Bu kanaldan gelen P1 bildirimleri de mutlaka talebe dönüştürülür.
- Durum sayfası: status.nebulacrm.example adresi bakım ve kesinti duyuruları içindir; talep kabul etmez.

Telefonla gelen her görüşme için talep kaydı açmak zorunludur. Kayıt açılmadan verilen destek SLA ölçümüne girmez ve kalite örneklemesinde görünmez.

## 3. Öncelik tanımları

Öncelik, müşterinin seçtiği değere göre değil, aşağıdaki etki tanımlarına göre L1 uzmanı tarafından belirlenir. Müşteri önceliğe itiraz ederse vaka bir üst kademeye danışılır.

| Öncelik | Tanım | Örnek |
| --- | --- | --- |
| P1 – Kritik | Üretim ortamı kullanılamıyor veya veri kaybı riski var | Tüm kullanıcılar giriş yapamıyor |
| P2 – Yüksek | Ana iş akışı ciddi biçimde aksıyor, geçici çözüm yok | Teklif oluşturma tüm ekipte hata veriyor |
| P3 – Normal | İşlev kısmen etkileniyor, geçici çözüm mevcut | Tek bir rapor yanlış filtre uyguluyor |
| P4 – Düşük | Soru, yapılandırma talebi veya iyileştirme önerisi | Alan etiketinin değiştirilmesi |

## 4. Destek kademeleri

### 4.1 L1 – İzmir Müşteri Destek Merkezi

L1 ekibi İzmir Bayraklı'daki merkezde vardiyalı çalışır. Hafta içi gündüz vardiyası 08:00–16:00, akşam vardiyası 12:00–20:00 saatleri arasındadır. Kurumsal ve Kurumsal Plus P1 talepleri için gece ve hafta sonu nöbeti İzmir ekibinden iki uzmanla tutulur. L1, taleplerin yaklaşık dörtte üçünü kendi kademesinde çözer; hedef L1 çözüm oranı %75'tir.

### 4.2 L2 – Ürün uzmanları

L2 ekibi İstanbul'da çalışan ürün uzmanlarından oluşur. Entegrasyon, raporlama, yetki yapılandırması ve veri içe aktarma konularında derin bilgiye sahiptir. L2, bir hatanın yazılım kusuru olduğunu doğruladığında Ar-Ge'ye NCRM önekli bir kusur kaydı açar ve talebi bu kayda bağlar.

### 4.3 L3 – Ar-Ge nöbet ekibi

L3, Ar-Ge'nin haftalık nöbet çizelgesindeki mühendislerden oluşur. L3'e yalnızca L2 üzerinden ulaşılır; L1'in doğrudan Ar-Ge'yi araması yalnızca ilan edilmiş bir Sev-1 olayında serbesttir.

## 5. Eskalasyon kuralları

1. Süre bazlı eskalasyon: P1 talep 45 dakika içinde L1'de çözülemezse L2'ye aktarılır; P2 talepler için bu süre 4 saattir.
2. Kusur eskalasyonu: Yazılım kusuru şüphesi olan her talep, L1 tarafından tekrar adımlarıyla birlikte L2'ye aktarılır. L2 doğrulamadan Ar-Ge'ye kayıt açılmaz.
3. Yönetim eskalasyonu: Bir Kurumsal veya Kurumsal Plus müşterisi aynı takvim ayında iki SLA ihlali yaşarsa Can Öztürk bilgilendirilir ve atanmış Müşteri Başarı Uzmanı 1 iş günü içinde müşteriyle görüşür.
4. Olay eskalasyonu: Aynı belirtiyle 15 dakika içinde en az 5 farklı müşteriden talep gelirse vardiya sorumlusu olası bir olay bildirir ve DevOps nöbetçisine haber verir.

Sev-1 olarak ilan edilen kesintilerde müşterilere ilk kamuya açık bildirim, olay ilanından sonra 15 dakika içinde durum sayfasında yayımlanır ve olay sürdükçe her 30 dakikada bir güncellenir. Olay sonrası müşteri bilgilendirme metni Müşteri Deneyimi ile DevOps tarafından birlikte onaylanır.

## 6. Talep yaşam döngüsü

- Yeni: Talep oluşturuldu, öncelik henüz atanmadı.
- Açık: Öncelik atandı, uzman üzerinde çalışıyor.
- Müşteri Yanıtı Bekleniyor: Uzman müşteriden bilgi istedi; bu süre çözüm süresinden düşülür.
- Ar-Ge'de: Talep bir NCRM kusur kaydına bağlandı.
- Çözüldü: Uzman çözümü iletti; müşteri yeniden açabilir.
- Kapandı: Talep kapandı; yeniden açılamaz, yeni talep açılır.

Müşteri Yanıtı Bekleniyor durumunda kalan talepler için 3. ve 6. günde otomatik hatırlatma gönderilir; müşteri yanıt vermezse talep 7 gün sonunda otomatik olarak kapanır. Çözüldü durumundaki talep 72 saat içinde yeniden açılmazsa Kapandı durumuna geçer.

Talep kapandıktan 1 saat sonra müşteriye 5 puanlık memnuniyet (CSAT) anketi gönderilir. 1 veya 2 puan veren müşteriler için vardiya sorumlusu 2 iş günü içinde geri arama yapar.

## 7. Dil desteği

Destek Türkçe ve İngilizce verilir. DACH bölgesindeki müşterilere Almanca destek, Berlin'deki Nebula Technology GmbH ekibi tarafından hafta içi 09:00–17:00 (CET) saatleri arasında sunulur. Almanca taleplerde de öncelik tanımları ve eskalasyon kuralları aynen uygulanır.

## 8. Kalite güvencesi

Her hafta kapanan taleplerin %5'i rastgele seçilerek kalite formuyla puanlanır. Form; doğru önceliklendirme, teknik doğruluk, üslup ve kayıt eksiksizliği olmak üzere dört başlıktan oluşur. Ekip hedefi 100 üzerinden en az 85 puandır. Örneklemeyi Derya Kılıç koordine eder; sonuçlar aylık ekip toplantısında paylaşılır.

Müşteri ekran paylaşımlarında kişisel veri görülebileceğinden oturum kayıtları yalnızca müşteri onayıyla alınır ve KVKK Kişisel Veri Saklama ve İmha Politikası'ndaki sürelere göre saklanır. Talep notlarına parola, API anahtarı veya kart bilgisi yazılmaz; yanlışlıkla yazılırsa not derhal maskelenir.

## 9. Sürüm geçmişi

| Sürüm | Tarih | Değişiklik |
| --- | --- | --- |
| 4.0 | 03.03.2025 | Otomatik kapanma süresi 10 gün olarak belirlendi |
| 4.1 | 01.09.2025 | İzmir L1 merkezi ve vardiya düzeni eklendi |
| 5.0 | 02.03.2026 | Otomatik kapanma süresi 10 günden 7 güne indirildi |
| 5.0 | 02.03.2026 | Almanca destek ve özel kanal tanımları eklendi |
