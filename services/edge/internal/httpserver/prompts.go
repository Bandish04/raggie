// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"strings"

	"github.com/alicangunduz/raggie/services/edge/internal/locale"
)

// Localized helper prompts and short server-authored notes. The template
// language follows the request locale (see locale.Resolve); prompts that
// produce user-visible text tell the model to use the language of the user's
// input, so a Turkish question still gets a Turkish answer under the English
// template and vice versa.

// requestLocale returns the locale stored on the request context (set by the
// withLocale middleware and refined by the chat handler).
func requestLocale(ctx context.Context) locale.Locale {
	return locale.FromContext(ctx, locale.EN)
}

// memoryExtractionPrompt asks for ONLY durable, explicitly stated facts about
// the user (name, role, team, preferences), one per line, or NONE.
var memoryExtractionPrompt = map[locale.Locale]string{
	locale.EN: `Below is a single conversation turn between a user and an assistant. Extract DURABLE facts about the user that will be useful in FUTURE conversations (e.g. their name, title, team, preferences, responsibilities). Take only lasting facts the user stated EXPLICITLY; do NOT take temporary requests, questions or guesses. Write each fact on its own line, briefly, in the third person (e.g. "The user's name is Ali"), in the language the user wrote in. If there is no durable fact to extract, reply with only NONE.`,
	locale.TR: `Aşağıda bir kullanıcı ile asistan arasındaki tek bir konuşma turu var. Kullanıcı hakkında GELECEK sohbetlerde işe yarayacak KALICI bilgileri çıkar (ör. adı, ünvanı, ekibi, tercihleri, sorumlulukları). Yalnızca kullanıcının AÇIKÇA belirttiği, kalıcı bilgileri al; geçici istekleri, soruları veya tahminleri ALMA. Her bilgiyi tek satırda, kısa ve üçüncü tekil şahısla, kullanıcının yazdığı dilde yaz (ör. "Kullanıcının adı Ali"). Çıkarılacak kalıcı bilgi yoksa yalnızca NONE yaz.`,
}

// memoryTranscriptLabels label the two sides of the turn fed to extraction.
var memoryTranscriptLabels = map[locale.Locale][2]string{
	locale.EN: {"USER: ", "ASSISTANT: "},
	locale.TR: {"KULLANICI: ", "ASİSTAN: "},
}

// memoryBlockHeader introduces remembered facts in the system prompt.
var memoryBlockHeader = map[locale.Locale]string{
	locale.EN: "Facts remembered about the user from earlier conversations (use them if relevant):",
	locale.TR: "Kullanıcı hakkında önceki sohbetlerden hatırlananlar (gerekirse kullan):",
}

// memoryBlock renders remembered facts as a system-prompt block.
func memoryBlock(loc locale.Locale, facts []string) string {
	return locale.Pick(memoryBlockHeader, loc) + "\n- " + strings.Join(facts, "\n- ")
}

// subQueryPrompt asks the model to decompose a question into several focused
// web-search queries (one per line) in the question's language, each covering
// a DISTINCT angle so the gathered results are genuinely diverse.
var subQueryPrompt = map[locale.Locale]string{
	locale.EN: `Generate 6 focused search queries to research the user's question IN DEPTH on the web. The queries must cover DIFFERENT aspects, each from its own angle:
1. Background / definition (what the topic is, core concepts)
2. Current state / latest developments (newest data, recent news)
3. Key actors or comparisons (who/what stands out, comparison with alternatives)
4. Figures / statistics / numbers
5. Risks, criticism or challenges
6. Practical examples / applications / case studies

Write the queries IN THE LANGUAGE OF THE QUESTION. Put each query on its OWN line; do NOT add numbering, bullets, quotes or explanations — write only the search queries themselves.`,
	locale.TR: `Kullanıcının sorusunu web'de DERİNLEMESİNE araştırmak için 6 odaklı arama sorgusu üret. Sorgular birbirinden FARKLI yönleri kapsasın; her biri ayrı bir açıdan baksın:
1. Arka plan / tanım (konu nedir, temel kavramlar)
2. Güncel durum / en son gelişmeler (en yeni veriler, son haberler)
3. Kilit aktörler veya karşılaştırmalar (kim/ne öne çıkıyor, alternatiflerle kıyas)
4. Sayısal veriler / istatistikler / rakamlar
5. Riskler, eleştiriler veya zorluklar
6. Pratik örnekler / uygulamalar / vaka çalışmaları

Sorguları SORUNUN DİLİNDE yaz. Her sorguyu AYRI bir satıra koy; numara, madde işareti, tırnak veya açıklama EKLEME — yalnızca arama sorgularının kendisini yaz.`,
}

// webQueryPrompt turns a (possibly conversational) user message into ONE
// focused web-search query in the message's language.
var webQueryPrompt = map[locale.Locale]string{
	locale.EN: `Turn the user's message into ONE focused web search query. Write only the query to type into a search engine: do NOT add explanations, quotes, numbering or bullets. Write the query in the message's language and drop filler words; use the key terms that carry the gist of the topic.`,
	locale.TR: `Kullanıcının mesajını web'de aratmak için TEK bir odaklı arama sorgusuna dönüştür. Yalnızca arama motoruna yazılacak sorguyu yaz: açıklama, tırnak, numara veya madde işareti EKLEME. Sorguyu mesajın diliyle yaz ve gereksiz dolgu kelimeleri at; konunun özünü taşıyan anahtar terimleri kullan.`,
}

// searchPlanPrompt plans a web research turn as JSON. {COUNTRY} is replaced
// with the configured default search country (WEB_SEARCH_COUNTRY).
var searchPlanPrompt = map[locale.Locale]string{
	locale.EN: `Plan the user's question for web research. Return ONLY valid JSON:
{"queries":["<search query 1>","<search query 2>"],"country":"{COUNTRY}","search_lang":"auto","freshness":""}

Rules:
- queries should cover different search intents; the first query should be closest to the user's actual question.
- Write the queries in the user's language.
- country is usually {COUNTRY}; if another country is explicitly requested, use its ISO country code.
- If search_lang is unknown, write "auto".
- freshness is "pd", "pw", "pm" or "py" only when recency clearly matters; otherwise an empty string.`,
	locale.TR: `Kullanıcının sorusunu web araştırması için planla. YALNIZCA geçerli JSON döndür:
{"queries":["<arama sorgusu 1>","<arama sorgusu 2>"],"country":"{COUNTRY}","search_lang":"auto","freshness":""}

Kurallar:
- queries farklı arama niyetlerini kapsasın; ilk sorgu kullanıcının asıl sorusuna en yakın sorgu olsun.
- Sorguları kullanıcının dilinde yaz.
- country çoğunlukla {COUNTRY} olsun; açıkça başka ülke istenirse ISO ülke kodu yaz.
- search_lang bilinmiyorsa "auto" yaz.
- freshness yalnızca güncellik açıkça önemliyse "pd", "pw", "pm" veya "py" olsun; değilse boş string.`,
}

// followupQueryPrompt asks for up to two queries covering evidence gaps.
var followupQueryPrompt = map[locale.Locale]string{
	locale.EN: `The web research below has gathered initial evidence. Suggest at most 2 search queries for what is still MISSING to answer the user's question better. Return ONLY JSON:
{"queries":["<follow-up query>"]}

Write queries only if needed; if the evidence is sufficient, queries must be an empty array.`,
	locale.TR: `Aşağıdaki web araştırması ilk kanıtları topladı. Kullanıcının sorusunu daha iyi cevaplamak için EKSİK kalan en fazla 2 arama sorgusu öner. YALNIZCA JSON döndür:
{"queries":["<takip sorgusu>"]}

Sorgu gerekiyorsa yaz; yeterli kanıt varsa queries boş dizi olsun.`,
}

// scheduleParsePrompt turns a natural-language schedule request into
// structured fields. {NOW} and {TZ} are substituted at runtime.
var scheduleParsePrompt = map[locale.Locale]string{
	locale.EN: `You are a parser that turns the user's natural-language scheduling request into a structured scheduled task.

Current time: {NOW} ({TZ} time zone).

Extract the following from the request and return ONLY a valid JSON object (no other text, explanation or code block before/after it):
{"cron":"<standard 5-field cron: minute hour day-of-month month day-of-week>","prompt":"<what the assistant does on every run; clear, complete, without the timing phrase>","name":"<short name for the task>","summary":"<human-readable summary, e.g. Every day at 09:00>"}

Rules:
- The cron is interpreted in the {TZ} time zone.
- If ambiguous, assume sensibly: "every morning"/"every day" = 09:00; "weekdays" = Monday-Friday; "every week" = Monday 09:00; "every month" = the 1st at 09:00.
- prompt describes only the work to do; keep the timing phrase out of it.
- Write name, prompt and summary in the language of the user's request; cron is numeric.
- Even for a nonsensical request, produce the closest sensible cron.`,
	locale.TR: `Sen, kullanıcının doğal dildeki zamanlama isteğini yapılandırılmış bir zamanlanmış göreve çeviren bir ayrıştırıcısın.

Şu anki zaman: {NOW} ({TZ} saat dilimi).

Kullanıcının isteğinden aşağıdakileri çıkar ve YALNIZCA geçerli bir JSON nesnesi döndür (öncesinde/sonrasında başka metin, açıklama ya da kod bloğu OLMASIN):
{"cron":"<5 alanlı standart cron: dakika saat ayıngünü ay haftanıngünü>","prompt":"<asistanın her çalıştırmada yapacağı iş; net, eksiksiz, zamanlama ifadesi olmadan>","name":"<görev için kısa ad>","summary":"<insan için okunur özet, örn. Her gün 09:00>"}

Kurallar:
- cron, {TZ} saat dilimine göre yorumlanır.
- Belirsizse makul varsay: "her sabah"/"her gün" = 09:00; "hafta içi" = Pazartesi-Cuma; "her hafta" = Pazartesi 09:00; "her ay" = ayın 1'i 09:00.
- prompt yalnızca yapılacak işi anlatsın; zamanlama ifadesini prompt'a koyma.
- name, prompt ve summary kullanıcının isteğinin dilinde olsun; cron sayısaldır.
- Anlamsız istekte bile en yakın makul cron'u üret.`,
}

// skillInstructionsPrompt turns a short description into a skill's system
// prompt (the instructions the assistant follows when the skill is selected).
var skillInstructionsPrompt = map[locale.Locale]string{
	locale.EN: `You are an expert prompt engineer for Raggie, an enterprise document assistant. Raggie answers questions over the user's OWN documents (RAG).

The user wants to create a "skill" (a ready-made assistant preset) and will briefly describe what it should do. Your task: write a high-quality, clear SYSTEM PROMPT (instructions) that the assistant follows when that skill is selected.

Rules:
- Write ONLY the system prompt itself. Do NOT add explanations, titles, preambles, quotes or lead-ins like "Here it is:".
- Write in the same language as the user's description.
- Start with a clear role sentence ("You are …").
- Define the assistant's goal, the steps it follows and the output format (headings, bullets or tables where useful).
- Stay true to Raggie's nature: answers are grounded in the user's documents; it never invents information that is not in them; when information is missing it says so politely.
- Keep it professional, actionable and concise (about 5-10 sentences or bullets). No unnecessary embellishment.`,
	locale.TR: `Sen, kurumsal doküman-asistanı Raggie için uzman bir prompt mühendisisin. Raggie, kullanıcının KENDİ belgeleri üzerinden (RAG) soruları yanıtlayan bir asistandır.

Kullanıcı bir "skill" (hazır asistan ön-ayarı) oluşturmak istiyor ve ne yapmasını istediğini kısaca anlatacak. Görevin: o skill seçildiğinde asistanın izleyeceği, yüksek kaliteli ve net bir SİSTEM PROMPTU (talimatlar) yazmak.

Kurallar:
- SADECE sistem promptunun kendisini yaz. Açıklama, başlık, ön-söz, tırnak işareti ya da "İşte:" gibi ekler KOYMA.
- Kullanıcının açıklamasıyla aynı dilde yaz.
- Net bir rol cümlesiyle başla ("Sen ...sın").
- Asistanın amacını, izleyeceği adımları ve çıktının biçimini (gerektiğinde başlık, madde işaretleri veya tablo) tanımla.
- Raggie'nin doğasına sadık kal: yanıtlar kullanıcının belgelerine dayanır; belgelerde olmayan bilgiyi uydurmaz; bilgi eksikse nazikçe belirtir.
- Profesyonel, uygulanabilir ve öz tut (yaklaşık 5-10 cümle veya madde). Gereksiz süsleme yok.`,
}

// visionDropNote is appended to the user turn when the chat model cannot take
// images, so the model — and the user — know the attachment was ignored.
var visionDropNote = map[locale.Locale]string{
	locale.EN: "\n\n(Note: the attached image(s) were ignored because this chat model does not support image input.)",
	locale.TR: "\n\n(Not: bu sohbet modeli görsel girdisini desteklemediği için eklenen görsel(ler) yok sayıldı.)",
}

// iterLimitNote is the answer used when the agentic loop exhausts its
// iteration cap without producing an answer.
var iterLimitNote = map[locale.Locale]string{
	locale.EN: "Sorry, I reached the limit of tool steps needed to complete this request. Please narrow your question and try again.",
	locale.TR: "Üzgünüm, bu isteği tamamlamak için gereken araç adımlarının sınırına ulaştım. Lütfen sorunuzu daraltıp tekrar deneyin.",
}

// iterLimitThinkingNote is shown on the reasoning channel when the cap hits.
var iterLimitThinkingNote = map[locale.Locale]string{
	locale.EN: "\n(Tool call limit reached.)",
	locale.TR: "\n(Araç çağrısı sınırına ulaşıldı.)",
}

// webPageContentLabel prefixes a fetched page excerpt in web evidence. Like the
// passage labels it is a language-neutral machine label.
const webPageContentLabel = "Page content: "

// searchPlanFor renders the search-plan prompt with the default country.
func searchPlanFor(loc locale.Locale, country string) string {
	if strings.TrimSpace(country) == "" {
		country = "US"
	}
	return strings.ReplaceAll(locale.Pick(searchPlanPrompt, loc), "{COUNTRY}", strings.ToUpper(country))
}
