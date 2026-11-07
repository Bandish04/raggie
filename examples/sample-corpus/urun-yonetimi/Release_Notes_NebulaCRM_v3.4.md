# NebulaCRM v3.4 Release Notes

General availability: 15 September 2026

- Document No: URN-RN-034
- Version: 3.4.0
- Owner: Merve Doğan (Product Manager)
- Prepared by: İrem Korkmaz (Product Owner)
- Previous release: 3.3.0 (12 May 2026)
- Issue Date: 2026-09-15
- Classification: Internal

## Highlights

NebulaCRM v3.4 became generally available on 15 September 2026. This release makes Nebula Assist, our AI assistant, generally available, rebuilds report export from the ground up, adds a native telephony connector and gives customers in the DACH region a self-service path to the FRA-1 EU region. The rollout was completed for all tenants by 18 September 2026 without downtime.

## Nebula Assist is generally available

Nebula Assist answers questions about accounts, deals and activities, summarises calls and drafts follow-up e-mails. Every answer cites the CRM records it was built from, and the assistant only sees records the user is already allowed to open. Customer data is never used to train models.

- Included in Kurumsal (500 requests per user per month) and Kurumsal Plus (1,500 requests per user per month).
- Available for Profesyonel as an add-on at TRY 240 per user per month.
- Languages: Turkish, English and German.
- Administrators can switch the assistant off per tenant or per role in Settings > Nebula Assist.

Assist moves out of the beta that started on 1 July 2026 with 40 pilot customers. Usage during the beta is not counted against the new monthly quotas.

## Report export, rebuilt

Report export now runs on a streaming engine instead of building the whole file in memory. In our benchmark a report with 1 million rows exports to CSV in under 90 seconds; in v3.3, exports above 200,000 rows could time out. XLSX exports are capped at the format's own limit of 1,048,576 rows per sheet. Large exports continue in the background and the user is notified when the file is ready to download; download links expire after 7 days.

## Native CTI telephony connector

NebulaCRM v3.4 introduces a native CTI telephony connector. Calls placed or received through a SIP-based call-centre system are logged automatically on the matching contact, with duration, direction and outcome. Click-to-call works from contact and deal cards. The connector is available on Profesyonel and above and is configured by an administrator in Settings > Integrations > Telephony.

## EU data residency: FRA-1 tenant migration

The FRA-1 region in Frankfurt opened for new DACH customers on 1 July 2026. With v3.4, existing tenants can request migration to FRA-1 from the admin console. Migrations are scheduled with the customer's Technical Account Manager or the support team; the tenant is read-only for at most 30 minutes during the final cut-over. Data is copied, verified and then deleted from the source region within 14 days.

## Limits

| Limit | v3.3 | v3.4 |
| --- | --- | --- |
| Bulk import (per file) | 50,000 rows | 100,000 rows |
| CSV report export | about 200,000 rows | 1,000,000+ rows |
| Nebula Assist requests (Kurumsal) | Beta only | 500 per user per month |
| Nebula Assist requests (Kurumsal Plus) | Beta only | 1,500 per user per month |

Bulk import now accepts up to 100,000 rows per file, up from 50,000 rows in v3.3. API rate limits are unchanged; see the NebulaCRM API v3 Reference.

## Notes for administrators

- Nebula Assist is enabled by default for Kurumsal and Kurumsal Plus tenants that took part in the beta; all other eligible tenants must switch it on in Settings > Nebula Assist.
- Usage per user and per team is shown in Admin > Usage > Nebula Assist and can be exported.
- The telephony connector needs the call-centre system's SIP domain and an API credential; inbound calls from numbers that match no contact are logged as unassigned activities.
- FRA-1 migration requests are reviewed within 5 business days; a migration cannot be scheduled during the 15 December – 5 January release freeze.

## Mobile

- Offline mode: contacts, deals and notes from the last 30 days are available without a connection; changes sync automatically when the device is back online.
- Call logging from the mobile app uses the new CTI connector when it is enabled.
- Minimum supported mobile OS versions are now the two most recent major releases.

## Fixed issues

- NCRM-5120: Report exports above 200,000 rows timed out (replaced by the streaming engine).
- NCRM-5177: Mobile sync could duplicate notes created while switching networks.
- NCRM-5203: Webhook deliveries for deal.stage_changed were sent twice after a manual retry.
- NCRM-5246: Multi-currency quotes rounded EUR totals incorrectly when a line discount was applied.

## Deprecations and upcoming changes

- API v2 will be switched off on 31 March 2027. Customers still calling v2 endpoints receive a Deprecation response header and a monthly reminder e-mail.
- The legacy report export endpoint will be removed in v3.5; use the asynchronous export API.
- NebulaCRM v3.5 is planned for 8 December 2026.
