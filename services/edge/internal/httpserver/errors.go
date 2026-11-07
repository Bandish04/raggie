// SPDX-License-Identifier: Apache-2.0

package httpserver

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/alicangunduz/raggie/services/edge/internal/locale"
)

// Error contract (client-facing), shared by every edge endpoint.
//
// Before any SSE byte is written, a failure is a JSON body with the status
// code below:
//
//	{"error":"<code>","code":"<code>","message":"<user-safe text>"}
//
// `code` (mirrored in the legacy `error` field) is stable for client
// branching and translation; `message` is a user-safe default in the request
// locale (English unless the request asks otherwise) and never carries
// internal detail. After SSE headers are sent the status cannot change, so a
// failure becomes an SSE `event: error` with {"code","message"}.
const (
	errCodeBusy        = "busy"              // 503 — outbound pool at capacity (A5 load shedding)
	errCodeRetrieval   = "retrieval_error"   // 502 — retrieval/embedding/vector store failed
	errCodeUpstream    = "upstream_error"    // 502 — chat LLM upstream failed to start
	errCodeBadRequest  = "bad_request"       // 400 — malformed body / missing fields
	errCodeTooLarge    = "payload_too_large" // 413 — body exceeds its size cap
	errCodeNotFound    = "not_found"         // 404 — unknown workspace/conversation/message
	errCodeUnauth      = "unauthorized"      // 401 — missing/invalid credentials
	errCodeForbidden   = "forbidden"         // 403 — no access to the resource / origin
	errCodeConflict    = "conflict"          // 409 — duplicate idempotency key
	errCodeRateLimited = "rate_limited"      // 429 — per-user/session/IP limit hit (Retry-After set)
	errCodeDraining    = "draining"          // 503 — replica shutting down; retry (Retry-After set)
	errCodeUnavailable = "unavailable"       // 503 — feature not configured
	errCodeInternal    = "internal_error"    // 5xx — unexpected server-side failure
	errCodeParseFailed = "parse_failed"      // 422 — the model could not parse the request (schedule)
	errCodeStream      = "stream_error"      // mid-stream failure (SSE event: error)
)

// errMessages holds the user-safe default message per code and locale.
var errMessages = map[string]map[locale.Locale]string{
	errCodeBusy: {
		locale.EN: "The system is busy right now. Please try again in a few seconds.",
		locale.TR: "Sistem şu anda yoğun. Lütfen birkaç saniye sonra tekrar deneyin.",
	},
	errCodeRetrieval: {
		locale.EN: "I couldn't prepare your answer right now. Please try again.",
		locale.TR: "Şu anda yanıtınızı oluşturamadım. Lütfen tekrar deneyin.",
	},
	errCodeUpstream: {
		locale.EN: "I couldn't prepare your answer right now. Please try again.",
		locale.TR: "Şu anda yanıtınızı oluşturamadım. Lütfen tekrar deneyin.",
	},
	errCodeBadRequest: {
		locale.EN: "The request is invalid. Please check your message and try again.",
		locale.TR: "İstek geçersiz. Lütfen mesajınızı kontrol edip tekrar deneyin.",
	},
	errCodeTooLarge: {
		locale.EN: "The request is too large. Please shorten the message or attachments and try again.",
		locale.TR: "İstek çok büyük. Lütfen mesajı veya ekleri küçültüp tekrar deneyin.",
	},
	errCodeNotFound: {
		locale.EN: "The requested item was not found.",
		locale.TR: "İstenen öğe bulunamadı.",
	},
	errCodeUnauth: {
		locale.EN: "Your session could not be verified. Please sign in again.",
		locale.TR: "Oturum doğrulanamadı. Lütfen tekrar giriş yapın.",
	},
	errCodeForbidden: {
		locale.EN: "You don't have permission to do this.",
		locale.TR: "Bu işlem için yetkiniz yok.",
	},
	errCodeConflict: {
		locale.EN: "This request is already being processed.",
		locale.TR: "Bu istek zaten işleniyor.",
	},
	errCodeRateLimited: {
		locale.EN: "Too many requests. Please wait a moment and try again.",
		locale.TR: "Çok fazla istek gönderdiniz. Lütfen biraz bekleyip tekrar deneyin.",
	},
	errCodeDraining: {
		locale.EN: "The server is restarting. Please try again in a few seconds.",
		locale.TR: "Sunucu yeniden başlatılıyor. Lütfen birkaç saniye sonra tekrar deneyin.",
	},
	errCodeUnavailable: {
		locale.EN: "This service is currently unavailable. Please try again later.",
		locale.TR: "Bu servis şu anda kullanılamıyor. Lütfen daha sonra tekrar deneyin.",
	},
	errCodeInternal: {
		locale.EN: "Something went wrong. Please try again.",
		locale.TR: "Bir sorun oluştu. Lütfen tekrar deneyin.",
	},
	errCodeParseFailed: {
		locale.EN: "I couldn't understand your request. Please phrase it more clearly.",
		locale.TR: "İsteğinizi anlayamadım, lütfen daha açık yazın.",
	},
	errCodeStream: {
		locale.EN: "Something went wrong while generating the answer. Please try again.",
		locale.TR: "Yanıt oluşturulurken bir sorun oluştu. Lütfen tekrar deneyin.",
	},
}

// errorMessage returns the message for code in the request's locale.
func errorMessage(ctx context.Context, code string) string {
	return locale.Pick(errMessages[code], locale.FromContext(ctx, locale.EN))
}

// writeError writes the JSON error contract. Use ONLY before any SSE bytes
// have been written.
func writeError(w http.ResponseWriter, r *http.Request, status int, code string) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"error": code, "code": code, "message": errorMessage(r.Context(), code),
	})
}

// writeStreamError emits an SSE `event: error` so the client can render a
// graceful note after streaming has already started. Caller flushes.
func writeStreamError(w http.ResponseWriter, r *http.Request, code string) {
	data, _ := json.Marshal(map[string]string{"code": code, "message": errorMessage(r.Context(), code)})
	fmt.Fprintf(w, "event: error\ndata: %s\n\n", data)
}

// withLocale seeds every request's context with a locale from Accept-Language
// (else defaultLocale) so error messages are localized even before a handler
// knows more. The chat handler refines it with the explicit locale field and
// the user's stored preference.
func withLocale(defaultLocale locale.Locale) middleware {
	if defaultLocale == "" {
		defaultLocale = locale.EN
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			l := locale.Resolve(locale.Inputs{AcceptLanguage: r.Header.Get("Accept-Language")}, defaultLocale)
			next.ServeHTTP(w, r.WithContext(locale.WithContext(r.Context(), l)))
		})
	}
}
