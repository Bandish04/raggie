# SPDX-License-Identifier: Apache-2.0

"""Ar-Ge (R&D) department documents."""

from model import H1, H2, OL, UL, D, Doc, P, T

ARCHITECTURE = Doc(
    path="arge/Teknik_Mimari_NebulaCRM_2026.pdf",
    title="NebulaCRM Teknik Mimari Dokümanı",
    subtitle="Platform bileşenleri, veri katmanı, çok kiracılı yapı ve ortamlar — 2026 revizyonu",
    lang="tr",
    date=D(2026, 10, 5),
    doc_no="ARGE-MIM-001",
    meta=(
        ("Sürüm", "4.1"),
        ("Sahibi", "Ayşe Demir, Ar-Ge Müdürü"),
        ("Hazırlayan", "Okan Yıldız, Kıdemli Yazılım Mühendisi"),
        ("Onaylayan", "Mehmet Yılmaz, CEO"),
    ),
    blocks=(
        H1("1. Amaç ve Kapsam"),
        P(
            "Bu doküman NebulaCRM platformunun 2026 yılı itibarıyla üretimde çalışan mimarisini "
            "tanımlar. Yeni katılan mühendislerin oryantasyonu, mimari karar kayıtlarının (ADR) "
            "bağlamı ve dış denetimlerde sorulan teknik sorular için referans kaynaktır. Doküman "
            "her yıl en az bir kez ve büyük bir altyapı değişikliğinden sonra güncellenir; 4.1 "
            "revizyonu FRA-1 bölgesinin devreye alınması ve Eylül 2026 trafik ölçümleri üzerine "
            "hazırlanmıştır."
        ),
        P(
            "Kapsam dışı konular: kurumsal BT altyapısı (ofis ağı, uç cihazlar) BT Müdürlüğü'nün "
            "dokümanlarında, yedekleme ve felaket kurtarma süreçleri ise ayrı bir planda ele "
            "alınır. Bu dokümanda yalnızca ürünün çalışma zamanı mimarisi anlatılmaktadır."
        ),
        H1("2. Genel Bakış"),
        P(
            "NebulaCRM, Kubernetes 1.30 üzerinde koşan 34 mikroservisten oluşur. Çekirdek iş "
            "mantığı (müşteri, fırsat, teklif, aktivite, faturalama servisleri) Go ile, web "
            "arayüzü ve arayüze özel BFF (backend-for-frontend) katmanı TypeScript ile "
            "yazılmıştır. Servisler arası senkron iletişim gRPC, asenkron iletişim ise olay "
            "veriyolu üzerinden yürür. Dış dünyaya açılan tek giriş noktası API ağ geçididir; "
            "REST API v3, web uygulaması ve mobil istemciler aynı ağ geçidini kullanır."
        ),
        T(
            ("Katman", "Teknoloji", "Not"),
            (
                ("Web arayüzü", "TypeScript", "BFF ile birlikte 3 servis"),
                ("Çekirdek servisler", "Go 1.23", "27 servis"),
                ("Veri/arka plan işleri", "Go", "4 servis"),
                ("Olay veriyolu", "Kafka, 3 broker", "Replikasyon faktörü 3"),
                ("İlişkisel veritabanı", "PostgreSQL 16", "1 birincil + 2 replika"),
                ("Önbellek", "Redis 7", "Oturum ve hız limiti"),
                ("Orkestrasyon", "Kubernetes 1.30", "Her bölgede ayrı küme"),
            ),
            caption="Tablo 1 — Platform katmanları (34 mikroservisin dağılımı: 3 + 27 + 4).",
            widths=(1.3, 1.3, 1.6),
        ),
        H1("3. Veri Katmanı"),
        H2("3.1 PostgreSQL"),
        P(
            "Ana işlemsel veri PostgreSQL 16 üzerinde tutulur. Her bölgede bir birincil sunucu ve "
            "iki okuma replikası bulunur; replikalar raporlama sorgularını ve arama indeksleme "
            "işlerini karşılar. Replikasyon akış tabanlıdır ve izlenen hedef gecikme 2 saniyenin "
            "altıdır. Bağlantılar her serviste ayrı bir bağlantı havuzu katmanı üzerinden "
            "yönetilir; birincil sunucuda eşzamanlı bağlantı üst sınırı 800 olarak "
            "ayarlanmıştır."
        ),
        P(
            "Şema değişiklikleri yalnızca geriye uyumlu (expand/contract) yöntemle yapılır. Bir "
            "kolonun silinmesi en az iki sürüm treni sonrasına bırakılır. 10 milyondan fazla "
            "satırı olan tablolara indeks eklemek için CONCURRENTLY kullanımı zorunludur ve bu "
            "değişiklikler mesai dışında, 22:00 sonrasında uygulanır."
        ),
        H2("3.2 Redis ve Kafka"),
        P(
            "Redis 7 kümesi oturum verisi, API hız limiti sayaçları ve kısa ömürlü önbellek için "
            "kullanılır; kalıcı veri Redis'te tutulmaz. Kafka kümesi 3 broker ile çalışır, "
            "konuların replikasyon faktörü 3, min.insync.replicas değeri 2'dir. Olaylar varsayılan "
            "olarak 7 gün saklanır; denetim (audit) olayları ise 30 gün tutulur ve ardından "
            "nesne depolamaya arşivlenir."
        ),
        H2("3.3 Arama"),
        P(
            "Tam metin arama için ayrı bir arama kümesi işletilir. İndeksleme, PostgreSQL "
            "replikalarından okunan değişiklik olaylarıyla beslenir; bir kaydın oluşturulmasından "
            "arama sonuçlarında görünmesine kadar geçen süre için hedef p95 değeri 5 saniyedir."
        ),
        H1("4. Çok Kiracılı Yapı ve İzolasyon"),
        P(
            "NebulaCRM paylaşımlı şema modeliyle çalışır: her tabloda tenant_id kolonu bulunur ve "
            "PostgreSQL satır düzeyi güvenlik (row-level security) politikaları her sorguda "
            "kiracı filtresini zorunlu kılar. Uygulama katmanı bağlantıyı açarken oturum "
            "değişkenine kiracı kimliğini yazar; bu değişken yoksa politika hiçbir satır "
            "döndürmez. Böylece uygulama kodundaki bir filtre hatası başka bir kiracının verisini "
            "sızdıramaz."
        ),
        P(
            "Kurumsal Plus müşterilerine ayrılmış (dedicated) veritabanı seçeneği sunulur. Bu "
            "seçenekte müşterinin verisi aynı kümede fakat yalnızca o müşteriye ait bir PostgreSQL "
            "örneğinde tutulur; uygulama servisleri paylaşımlı kalır. 30 Eylül 2026 itibarıyla 9 "
            "müşteri ayrılmış veritabanı seçeneğini kullanmaktadır."
        ),
        H1("5. Bölgeler ve Veri Merkezleri"),
        T(
            ("Bölge", "Konum", "Rol"),
            (
                ("IST-1", "İstanbul", "Birincil üretim"),
                ("ANK-DR1", "Ankara", "Felaket kurtarma"),
                ("FRA-1", "Frankfurt", "AB bölgesi (DACH)"),
            ),
            caption="Tablo 2 — Çalışma bölgeleri.",
            widths=(1, 1, 1.6),
        ),
        P(
            "IST-1 birincil üretim bölgesidir ve Türkiye'deki tüm müşteriler burada barındırılır. "
            "ANK-DR1 sıcak yedek olarak çalışır; veritabanı WAL kayıtları ve nesne depolama "
            "sürekli olarak buraya kopyalanır. FRA-1 bölgesi 1 Temmuz 2026'da açılmıştır ve "
            "DACH bölgesindeki yeni müşteriler için AB içinde veri yerleşimi sağlar. FRA-1, IST-1 "
            "ile aynı mimariyi daha küçük ölçekte çalıştırır; iki bölge arasında müşteri verisi "
            "kopyalanmaz."
        ),
        H1("6. Ortamlar ve Dağıtım"),
        P(
            "Üç ortam bulunur: dev, staging ve prod. Dev ortamı her birleştirmede (merge) otomatik "
            "güncellenir. Staging, üretimin anonimleştirilmiş veriyle beslenen birebir kopyasıdır "
            "ve sürüm adayları burada en az 48 saat bekletilir. Üretime dağıtım kademeli "
            "(canary) yapılır: yeni sürüm önce trafiğin %5'ini alır, 30 dakika boyunca hata oranı "
            "ve gecikme metrikleri eşik içinde kalırsa %50'ye, ardından %100'e çıkarılır."
        ),
        UL(
            "Konteyner imajları yalnızca CI hattında üretilir ve imzalanır; imzasız imaj üretim "
            "kümesine kabul edilmez.",
            "Altyapı tanımları kod olarak tutulur; elle yapılan küme değişiklikleri haftalık "
            "drift taramasında raporlanır.",
            "Sırlar (secrets) kasada saklanır ve podlara çalışma anında enjekte edilir.",
        ),
        H1("7. Kapasite ve Trafik"),
        P(
            "Eylül 2026'da ölçülen tepe trafik saniyede 2.400 istektir (RPS); bu değer 2025 "
            "yılının tepe değeri olan 1.650 RPS'ye göre belirgin bir artışı gösterir. Haziran "
            "2026 yük testinde platform 3.000 RPS'yi hedef gecikme içinde taşımıştır; ayrıntılar "
            "Ar-Ge yük testi raporundadır. Kapasite planlamasında tepe trafiğin en az 1,5 katı "
            "pay bırakılması kuralı uygulanır."
        ),
        H1("8. Gözlemlenebilirlik"),
        P(
            "Tüm servisler metrik, log ve dağıtık iz (trace) üretir. Uygulama logları 30 gün sıcak, "
            "1 yıl soğuk depolamada saklanır; kişisel veri içeren erişim logları için KVKK saklama "
            "politikasındaki süreler geçerlidir. Her servisin bir SLO tanımı vardır; çekirdek API için "
            "aylık erişilebilirlik hedefi %99,95 ve p95 gecikme hedefi 250 milisaniyedir. Nöbet "
            "(on-call) rotasyonu haftalıktır ve L3 destek talepleri bu rotasyondaki Ar-Ge "
            "mühendisine yönlendirilir."
        ),
        H1("9. Değişiklik Geçmişi"),
        T(
            ("Sürüm", "Tarih", "Değişiklik"),
            (
                ("3.0", "14.02.2025", "Kafka geçişi"),
                ("4.0", "10.02.2026", "Kubernetes 1.30, RLS"),
                ("4.1", "05.10.2026", "FRA-1, trafik verisi"),
            ),
            widths=(0.7, 1, 2),
        ),
    ),
)

LOAD_TEST = Doc(
    path="arge/Load_Test_Report_2026_Q2.docx",
    title="NebulaCRM Load Test Report — Q2 2026",
    subtitle="Capacity validation of the v3.3 platform ahead of the H2 2026 traffic forecast",
    lang="en",
    date=D(2026, 6, 12),
    doc_no="ARGE-PERF-2026-02",
    meta=(
        ("Version", "1.0 (final)"),
        ("Authors", "Hakan Bulut, Test Engineer; Okan Yıldız, Senior Software Engineer"),
        ("Reviewed by", "Ayşe Demir, R&D Manager"),
        ("Test window", "2–6 June 2026"),
    ),
    blocks=(
        H1("1. Executive summary"),
        P(
            "Between 2 and 6 June 2026 we ran a staged load test against a production-sized "
            "replica of the IST-1 environment running NebulaCRM v3.3. The goal was to confirm that "
            "the platform can sustain 3,000 requests per second (RPS) for 60 minutes with a p95 "
            "latency below 250 ms, which is the capacity we need for the second half of 2026."
        ),
        P(
            "The target was met. At 3,000 RPS sustained for 60 minutes the API recorded a p95 "
            "latency of 212 ms, a p99 latency of 480 ms and an error rate of 0.04%. The platform "
            "kept scaling until 4,150 RPS, where the primary PostgreSQL node reached 92% CPU and "
            "latency degraded sharply; we treat 4,150 RPS as the current breaking point."
        ),
        H1("2. Scope and method"),
        P(
            "The test environment mirrored production topology: 34 services on Kubernetes, one "
            "PostgreSQL 16 primary with two read replicas, a three-broker Kafka cluster and a Redis "
            "cluster. The dataset was a 1.8 TB anonymised snapshot taken on 20 May 2026, covering "
            "roughly 1,300 tenants."
        ),
        P(
            "Traffic was generated from 12 load-generator nodes replaying a request mix derived "
            "from one week of production access logs. Each step was held for 15 minutes, except "
            "the 3,000 RPS step, which was held for 60 minutes. Measurements were taken at the API "
            "gateway, so they include gateway, service and database time but not client network "
            "time."
        ),
        T(
            ("Request class", "Share of mix"),
            (
                ("Read (lists, record views)", "62%"),
                ("Search", "14%"),
                ("Write (create/update)", "19%"),
                ("Bulk/report endpoints", "5%"),
            ),
        ),
        H1("3. Results"),
        P(
            "Table 2 lists the results for each load step. Latency figures are measured at the "
            "API gateway; CPU is the peak utilisation of the PostgreSQL primary during the step."
        ),
        T(
            ("Step", "Target RPS", "p95 (ms)", "p99 (ms)", "Error rate", "DB CPU"),
            (
                ("S1", "1,000", "118", "240", "0.00%", "31%"),
                ("S2", "2,000", "151", "305", "0.01%", "49%"),
                ("S3", "3,000", "212", "480", "0.04%", "68%"),
                ("S4", "3,600", "287", "690", "0.11%", "81%"),
                ("S5", "4,150", "905", "2,400", "1.70%", "92%"),
            ),
        ),
        P(
            "At S4 (3,600 RPS) the platform still served traffic correctly but exceeded the 250 ms "
            "p95 target. At S5 (4,150 RPS) connection-pool waits on the primary dominated request "
            "time and the error rate climbed to 1.70%, mostly gateway timeouts. Kafka consumer lag "
            "stayed below 3 seconds in every step, and Redis was never a bottleneck."
        ),
        H2("3.1 Comparison with the 2025 baseline"),
        P(
            "The previous load test, run in Q2 2025 on v3.0, measured a p95 latency of 268 ms at "
            "2,000 RPS and broke at roughly 2,700 RPS. Today the same 2,000 RPS step completes with "
            "a p95 of 151 ms. Most of the gain comes from the read-replica routing introduced in "
            "v3.2 and from moving report generation off the primary database."
        ),
        T(
            ("Metric", "Q2 2025 (v3.0)", "Q2 2026 (v3.3)"),
            (
                ("p95 at 2,000 RPS", "268 ms", "151 ms"),
                ("Breaking point", "~2,700 RPS", "4,150 RPS"),
                ("Error rate at 2,000 RPS", "0.09%", "0.01%"),
            ),
        ),
        H2("3.2 Test configuration"),
        T(
            ("Component", "Configuration during the test"),
            (
                ("API gateway", "6 pods, autoscaling up to 18"),
                ("Core services", "Horizontal autoscaling at 65% CPU"),
                ("PostgreSQL primary", "64 vCPU, 512 GB RAM, NVMe"),
                ("Read replicas", "2 × 32 vCPU, 256 GB RAM"),
                ("Kafka", "3 brokers, 48 partitions on hot topics"),
                ("Load generators", "12 nodes, 4,000 virtual users max"),
            ),
        ),
        H2("3.3 Limitations"),
        P(
            "The results should be read with three limitations in mind. First, Nebula Assist was "
            "still in closed beta during the test window, so its traffic is not part of the request "
            "mix. Second, only the IST-1 topology was tested; FRA-1 runs a smaller footprint and "
            "will need its own test before it serves more than 100 tenants. Third, background "
            "jobs such as nightly report generation were paused, which slightly flatters database "
            "CPU figures at the higher steps."
        ),
        H1("4. Findings"),
        OL(
            "The PostgreSQL primary is the first component to saturate. Write traffic cannot be "
            "offloaded to replicas, and report queries that still hit the primary add load at "
            "peak.",
            "Two services (activity-timeline and quote-renderer) issue N+1 queries under load; "
            "fixing them is estimated to cut primary CPU by about 6 percentage points at 3,000 "
            "RPS.",
            "Autoscaling reacted within 90 seconds on every step, which is acceptable, but "
            "pod start-up for the search indexer takes 70 seconds and should be reduced.",
        ),
        H1("5. Recommendations"),
        UL(
            "Add two more PostgreSQL read replicas in IST-1 and route all reporting traffic to "
            "them. The estimated cost of the two extra DB replicas is TRY 840,000 for hardware "
            "and licences; this needs a purchase request under the finance approval matrix.",
            "Fix the N+1 queries in activity-timeline and quote-renderer before the v3.5 release.",
            "Repeat the test in Q4 2026 against v3.4 with Nebula Assist traffic included, "
            "targeting 3,600 RPS at p95 below 250 ms.",
            "Keep the current alert on primary CPU at 75% and add an alert on connection-pool "
            "wait time above 50 ms.",
        ),
        H1("6. Sign-off"),
        P(
            "Results were reviewed in the capacity meeting on 11 June 2026 and accepted by Ayşe "
            "Demir. Raw measurements and load-generator scripts are stored in the performance "
            "repository under perf/2026-q2."
        ),
    ),
)

API_REFERENCE = Doc(
    path="arge/NebulaCRM_API_v3_Reference.md",
    title="NebulaCRM REST API v3 — Developer Reference",
    subtitle="Authentication, rate limits, pagination, webhooks and errors for integrators",
    lang="en",
    date=D(2026, 9, 15),
    doc_no="ARGE-API-003",
    classification="Public",
    meta=(
        ("Version", "3.4 (aligned with NebulaCRM v3.4)"),
        ("Owner", "Okan Yıldız, Senior Software Engineer"),
        ("Contact", "api-support@nebulacrm.example"),
    ),
    blocks=(
        H1("1. Overview"),
        P(
            "The NebulaCRM REST API v3 gives programmatic access to contacts, companies, deals, "
            "quotes, activities and custom objects. All endpoints are served from the base URL "
            "https://api.nebulacrm.example/v3 over HTTPS (TLS 1.2 or later). Requests and "
            "responses use JSON encoded in UTF-8, and all timestamps are ISO 8601 in UTC."
        ),
        P(
            "Customers hosted in the EU region (FRA-1) use https://api.eu.nebulacrm.example/v3. "
            "The API surface is identical in both regions; tokens issued in one region are not "
            "valid in the other."
        ),
        H1("2. Authentication"),
        P(
            "Two authentication methods are supported. Server-to-server integrations should use "
            "the OAuth 2.0 client credentials flow; access tokens are valid for 60 minutes and "
            "are requested from https://auth.nebulacrm.example/oauth/token. Simple scripts and "
            "internal tools may use API keys instead."
        ),
        P(
            "API keys are created by a workspace administrator under Settings > Integrations. A "
            "live key has the form ncrm_live_ followed by 32 hexadecimal characters; sandbox keys "
            "use the prefix ncrm_test_. Send the key in the Authorization header as a bearer "
            "token. A key is shown only once at creation time, and unused keys are disabled "
            "automatically after 180 days without a request."
        ),
        H1("3. Rate limits"),
        P(
            "Rate limits are applied per token (per API key or per OAuth client) using a sliding "
            "one-minute window. Short bursts of up to twice the per-minute limit are tolerated "
            "for at most 10 seconds."
        ),
        T(
            ("Plan", "Requests per minute", "Max concurrent bulk jobs"),
            (
                ("Starter (Başlangıç)", "60", "1"),
                ("Professional (Profesyonel)", "300", "2"),
                ("Enterprise (Kurumsal)", "1,200", "5"),
                ("Enterprise Plus (Kurumsal Plus)", "3,000", "10"),
            ),
        ),
        P(
            "Every response carries the headers X-RateLimit-Limit, X-RateLimit-Remaining and "
            "X-RateLimit-Reset. When the limit is exceeded the API returns HTTP 429 with a "
            "Retry-After header giving the number of seconds to wait. Clients must honour "
            "Retry-After; tokens that keep sending requests while throttled for more than 15 "
            "minutes may be suspended."
        ),
        H1("4. Pagination"),
        P(
            "List endpoints use cursor-based pagination. The default page size is 50 records and "
            "the maximum is 200; pass the limit query parameter to change it. Each response "
            "includes a next_cursor field, which is null on the last page. Cursors expire after "
            "24 hours. Offset-based pagination from API v2 is not available in v3."
        ),
        H1("5. Idempotency"),
        P(
            "POST and PATCH requests accept an Idempotency-Key header (any unique string up to "
            "64 characters, a UUID is recommended). If the same key is sent again within 24 hours "
            "with the same body, the original response is returned and the operation is not "
            "repeated. Reusing a key with a different body returns 422 idempotency_conflict."
        ),
        H1("6. Webhooks"),
        P(
            "Webhooks deliver events such as deal.updated, contact.created and quote.accepted to "
            "an HTTPS endpoint you register. Each delivery is signed with HMAC-SHA256 using the "
            "endpoint's signing secret, and the signature is sent in the X-Nebula-Signature "
            "header together with a timestamp in X-Nebula-Timestamp. Reject deliveries whose "
            "timestamp is more than 5 minutes old to prevent replay."
        ),
        P(
            "Your endpoint must answer with a 2xx status within 10 seconds. Failed deliveries are "
            "retried 6 times with exponential backoff over roughly 24 hours, at 1 minute, 5 "
            "minutes, 30 minutes, 2 hours, 6 hours and 15 hours after the first attempt. After "
            "the sixth failed retry the event is dropped and the endpoint is flagged in the "
            "admin console; an endpoint that fails for 3 consecutive days is disabled."
        ),
        H1("7. Errors"),
        P(
            "Errors use standard HTTP status codes and a JSON body with code, message and "
            "request_id fields. Always log request_id; support needs it to trace a call."
        ),
        T(
            ("HTTP status", "code", "Meaning"),
            (
                ("400", "invalid_request", "Malformed JSON or missing field"),
                ("401", "unauthorized", "Missing, expired or revoked token"),
                ("403", "forbidden", "Token lacks the required scope"),
                ("404", "not_found", "Record does not exist in this tenant"),
                ("409", "conflict", "Record was modified concurrently"),
                ("422", "idempotency_conflict", "Idempotency-Key reused with another body"),
                ("429", "rate_limited", "Rate limit exceeded; see Retry-After"),
                ("503", "maintenance", "Planned maintenance window"),
            ),
        ),
        H1("8. Versioning and deprecation"),
        P(
            "Breaking changes are only introduced in a new major version. Additive changes (new "
            "fields, new endpoints) can ship in any release, so clients must ignore unknown "
            "fields. API v2 is deprecated and will be switched off on 31 March 2027 (sunset "
            "date); from 1 January 2027 every v2 response carries a Sunset header. Customers "
            "still on v2 should follow the migration guide on the developer portal."
        ),
        H1("9. Limits at a glance"),
        UL(
            "Maximum request body: 10 MB; bulk import files are uploaded separately.",
            "Maximum records per bulk import job: 100,000 rows (since v3.4).",
            "Maximum custom fields per object: 300.",
            "Search endpoint: at most 10,000 results per query; refine filters beyond that.",
        ),
    ),
)

CODE_REVIEW = Doc(
    path="arge/Engineering_Code_Review_Guidelines.txt",
    title="Engineering Code Review Guidelines",
    subtitle="How we branch, review and merge code in the NebulaCRM repositories",
    lang="en",
    date=D(2026, 2, 2),
    doc_no="ARGE-ENG-007",
    meta=(
        ("Version", "2.3"),
        ("Owner", "Ayşe Demir, R&D Manager"),
        ("Maintainer", "Okan Yıldız, Senior Software Engineer"),
        ("Effective", "2 February 2026"),
    ),
    blocks=(
        H1("1. Why we review"),
        P(
            "Code review is our main defence against defects reaching customers and our main way "
            "of sharing knowledge across the Istanbul and Ankara teams. A review is a "
            "conversation about the change, not a gate to be passed as fast as possible. These "
            "guidelines apply to every repository in the NebulaCRM organisation, including "
            "infrastructure code."
        ),
        H1("2. Branching"),
        UL(
            "main is always releasable. Nobody pushes to main directly; branch protection "
            "enforces this.",
            "Feature branches are named feature/NCRM-1234-short-desc, where NCRM-1234 is the "
            "work item key. Bug fixes use fix/NCRM-1234-short-desc.",
            "Branches older than 14 days without activity are reported in the weekly "
            "engineering digest and should be rebased or closed.",
            "Release branches are cut automatically as release/YYYY.MM.DD on the morning of "
            "each release train.",
        ),
        H1("3. Pull request size and description"),
        P(
            "Keep pull requests small. The soft limit is 400 changed lines, excluding generated "
            "files and lock files. Larger changes must be split, or the author must explain in "
            "the description why they cannot be. Every pull request description states what "
            "changed, why, how it was tested and how to roll it back."
        ),
        H1("4. Approvals"),
        P(
            "Changes in critical paths require 2 approvals: billing, authentication, tenancy and "
            "permission checks, data migrations and anything that touches encryption keys. At "
            "least one of the two approvers must be listed in the CODEOWNERS file for that path. "
            "All other changes require 1 approval. Authors cannot approve their own pull "
            "requests, and an approval is dismissed automatically when new commits are pushed."
        ),
        H1("5. Review turnaround"),
        P(
            "Reviewers give a first response within 1 business day. If a pull request has waited "
            "longer than that, the author may ask in the team channel for another reviewer. "
            "Small, urgent fixes can be reviewed synchronously in a short call, but the approval "
            "must still be recorded on the pull request."
        ),
        H1("6. What reviewers check"),
        OL(
            "Correctness: does the code do what the work item asks, including edge cases?",
            "Tenancy: every query that reads customer data is scoped by tenant_id; new tables "
            "have a row-level security policy.",
            "Tests: new code comes with unit tests; the release quality gate expects at least "
            "80% coverage on new code.",
            "Security: no secrets in code, input is validated, and new dependencies have been "
            "checked by the dependency scanner.",
            "Operability: logs, metrics and alerts are adequate, and the change can be rolled "
            "back.",
            "Readability: names, structure and comments make the next change easy.",
        ),
        H1("7. Merging"),
        P(
            "We use squash merge so that main has one commit per pull request; the squash commit "
            "message starts with the work item key. CI must be green before merging: build, unit "
            "and integration tests, linters, the dependency scanner and the static security "
            "scan. Merging with a failing check requires approval from the on-call lead and a "
            "follow-up work item."
        ),
        H1("8. Release train"),
        P(
            "We ship on a release train every 2 weeks on Tuesday. The release branch is cut at "
            "09:00 on release day from main; anything merged after that waits for the next "
            "train. Release candidates must pass the quality gate run by the Quality team "
            "before the Go/No-Go meeting at 14:00. No trains run during the year-end freeze."
        ),
        H1("9. Hotfixes"),
        P(
            "A hotfix is allowed only for a Sev-1 or Sev-2 production issue or a security fix "
            "that cannot wait for the next train. Hotfix branches are created from the latest "
            "release tag as hotfix/NCRM-1234-short-desc, need approval from the on-call lead in "
            "addition to the normal review rules, and are merged back into main within 1 "
            "business day after deployment. Every hotfix is listed in the weekly quality "
            "report."
        ),
        H1("10. Review etiquette"),
        UL(
            "Comment on the code, not the person. Prefer questions to commands.",
            "Mark optional suggestions with the prefix nit: so the author knows they do not "
            "block the merge.",
            "Resolve your own comments once they are addressed; do not leave threads open for "
            "the author to guess.",
            "If a discussion goes past three rounds, move it to a call and write the outcome "
            "on the pull request.",
        ),
        H1("11. Change log"),
        T(
            ("Version", "Date", "Change"),
            (
                ("2.1", "2025-03-03", "Branch naming convention"),
                ("2.2", "2025-09-15", "Tenancy check added"),
                ("2.3", "2026-02-02", "Two approvals for tenancy"),
            ),
        ),
    ),
)

DOCS = [ARCHITECTURE, LOAD_TEST, API_REFERENCE, CODE_REVIEW]
