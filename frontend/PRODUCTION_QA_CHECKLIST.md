# Instaagent Production QA Checklist

## Release Gates

- Backend starts cleanly on Render with no import errors.
- `python3 -m py_compile main_updated.py telegram_bot.py` passes before deploy.
- `python3 qa_smoke.py --api https://agent-1-xi6h.onrender.com --secret "$DASHBOARD_SECRET"` passes after deploy.
- Dashboard opens from HTTPS production URL, not only local `127.0.0.1`.
- `DASHBOARD_SECRET` is set in Render before exposing customer data.
- `CORS_ORIGINS` is set to the exact dashboard origins used in production.

## Core Messaging

- Instagram DM inbound message appears in dashboard without manual refresh.
- Instagram manual reply sends, appears in thread, and is persisted once.
- Telegram bot private message appears once and does not loop with bot-authored messages.
- Telegram bot blocked-user failure surfaces as `Forbidden: bot was blocked by the user (403)`.
- Telegram user-client message sends through `telegram_user_private`, not the bot API.
- WhatsApp inbound text appears and manual reply sends through WhatsApp Cloud.
- AI toggle persists per `business_id/platform/channel/customer_id`.

## Media

- Instagram image/video inbound renders a preview if Meta supplies a media URL.
- Telegram bot image/video/voice stores `media_url` or a recoverable file id.
- Telegram user-client photo renders through `/api/telegram-user-media/{customer_id}/{message_id}`.
- WhatsApp image/video/audio/document renders through `/api/whatsapp/media/{media_id}`.
- Private media endpoints require dashboard authorization when `DASHBOARD_SECRET` is set.

## Data And Schema

- `inbox_messages` has columns used by the app: `business_id`, `platform`, `customer_id`, `chat_id`, `customer_name`, `channel`, `direction`, `role`, `content`, `external_message_id`, `raw_payload`, `is_read`, `media_type`, `media_url`, `media_file_id`, `file_name`, `mime_type`, `whatsapp_media_id`.
- `chat_ai_settings` has a unique constraint on `business_id, platform, channel, customer_id`.
- Supabase service key is never exposed to browser code.
- Debug endpoints require dashboard secret.

## Reliability

- Webhook handlers are idempotent and deduplicate provider message IDs.
- Outbound messages are saved only after provider send success.
- Provider errors are returned with the original provider code/description.
- Frontend polling does not overlap requests and pauses when the browser tab is hidden.
- Render restart does not lose required Telegram user session state.

## Security

- No real access tokens appear in logs or API responses.
- OAuth redirect URIs exactly match Meta app settings.
- CORS does not use broad wildcard origins in production.
- Media proxy URLs are short-lived or protected.
- HTTPS-only dashboard URL is used for operators.

## UX Acceptance

- Active thread receives messages within 3 seconds.
- Inbox list updates unread count within 6 seconds.
- New inbound media shows a clear loading/preview/error state.
- Failed sends keep the typed text recoverable or display an actionable error.
- Mobile and desktop layouts have no overlapping controls.
