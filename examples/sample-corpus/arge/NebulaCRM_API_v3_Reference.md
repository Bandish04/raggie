# NebulaCRM REST API v3 — Developer Reference

Authentication, rate limits, pagination, webhooks and errors for integrators

- Document No: ARGE-API-003
- Version: 3.4 (aligned with NebulaCRM v3.4)
- Owner: Okan Yıldız, Senior Software Engineer
- Contact: api-support@nebulacrm.example
- Issue Date: 2026-09-15
- Classification: Public

## 1. Overview

The NebulaCRM REST API v3 gives programmatic access to contacts, companies, deals, quotes, activities and custom objects. All endpoints are served from the base URL https://api.nebulacrm.example/v3 over HTTPS (TLS 1.2 or later). Requests and responses use JSON encoded in UTF-8, and all timestamps are ISO 8601 in UTC.

Customers hosted in the EU region (FRA-1) use https://api.eu.nebulacrm.example/v3. The API surface is identical in both regions; tokens issued in one region are not valid in the other.

## 2. Authentication

Two authentication methods are supported. Server-to-server integrations should use the OAuth 2.0 client credentials flow; access tokens are valid for 60 minutes and are requested from https://auth.nebulacrm.example/oauth/token. Simple scripts and internal tools may use API keys instead.

API keys are created by a workspace administrator under Settings > Integrations. A live key has the form ncrm_live_ followed by 32 hexadecimal characters; sandbox keys use the prefix ncrm_test_. Send the key in the Authorization header as a bearer token. A key is shown only once at creation time, and unused keys are disabled automatically after 180 days without a request.

## 3. Rate limits

Rate limits are applied per token (per API key or per OAuth client) using a sliding one-minute window. Short bursts of up to twice the per-minute limit are tolerated for at most 10 seconds.

| Plan | Requests per minute | Max concurrent bulk jobs |
| --- | --- | --- |
| Starter (Başlangıç) | 60 | 1 |
| Professional (Profesyonel) | 300 | 2 |
| Enterprise (Kurumsal) | 1,200 | 5 |
| Enterprise Plus (Kurumsal Plus) | 3,000 | 10 |

Every response carries the headers X-RateLimit-Limit, X-RateLimit-Remaining and X-RateLimit-Reset. When the limit is exceeded the API returns HTTP 429 with a Retry-After header giving the number of seconds to wait. Clients must honour Retry-After; tokens that keep sending requests while throttled for more than 15 minutes may be suspended.

## 4. Pagination

List endpoints use cursor-based pagination. The default page size is 50 records and the maximum is 200; pass the limit query parameter to change it. Each response includes a next_cursor field, which is null on the last page. Cursors expire after 24 hours. Offset-based pagination from API v2 is not available in v3.

## 5. Idempotency

POST and PATCH requests accept an Idempotency-Key header (any unique string up to 64 characters, a UUID is recommended). If the same key is sent again within 24 hours with the same body, the original response is returned and the operation is not repeated. Reusing a key with a different body returns 422 idempotency_conflict.

## 6. Webhooks

Webhooks deliver events such as deal.updated, contact.created and quote.accepted to an HTTPS endpoint you register. Each delivery is signed with HMAC-SHA256 using the endpoint's signing secret, and the signature is sent in the X-Nebula-Signature header together with a timestamp in X-Nebula-Timestamp. Reject deliveries whose timestamp is more than 5 minutes old to prevent replay.

Your endpoint must answer with a 2xx status within 10 seconds. Failed deliveries are retried 6 times with exponential backoff over roughly 24 hours, at 1 minute, 5 minutes, 30 minutes, 2 hours, 6 hours and 15 hours after the first attempt. After the sixth failed retry the event is dropped and the endpoint is flagged in the admin console; an endpoint that fails for 3 consecutive days is disabled.

## 7. Errors

Errors use standard HTTP status codes and a JSON body with code, message and request_id fields. Always log request_id; support needs it to trace a call.

| HTTP status | code | Meaning |
| --- | --- | --- |
| 400 | invalid_request | Malformed JSON or missing field |
| 401 | unauthorized | Missing, expired or revoked token |
| 403 | forbidden | Token lacks the required scope |
| 404 | not_found | Record does not exist in this tenant |
| 409 | conflict | Record was modified concurrently |
| 422 | idempotency_conflict | Idempotency-Key reused with another body |
| 429 | rate_limited | Rate limit exceeded; see Retry-After |
| 503 | maintenance | Planned maintenance window |

## 8. Versioning and deprecation

Breaking changes are only introduced in a new major version. Additive changes (new fields, new endpoints) can ship in any release, so clients must ignore unknown fields. API v2 is deprecated and will be switched off on 31 March 2027 (sunset date); from 1 January 2027 every v2 response carries a Sunset header. Customers still on v2 should follow the migration guide on the developer portal.

## 9. Limits at a glance

- Maximum request body: 10 MB; bulk import files are uploaded separately.
- Maximum records per bulk import job: 100,000 rows (since v3.4).
- Maximum custom fields per object: 300.
- Search endpoint: at most 10,000 results per query; refine filters beyond that.
