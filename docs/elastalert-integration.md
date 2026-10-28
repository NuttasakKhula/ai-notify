# ElastAlert integration

Create an organization in the admin UI and securely save its one-time webhook key. Each organization uses its own key.

Copy `deploy/elastalert/custom_alerter.py` and `network_rule.yaml` into your existing ElastAlert2 mounted rules directory. The module must be importable as `rules.custom_alerter`. Store the key at `/opt/elastalert/rules/ai-notify-webhook.key`, readable by the runtime account only. Never commit its contents.

Attach API and ElastAlert to `ELK_NETWORK`. The rule posts to `http://ai-notify-api:8000/webhook/incident` over that private Docker network. Adapt index, query, device field and aggregation key to your log mapping. Mixed-device batches are rejected.

The adapter sends `X-Webhook-Key` and deterministic `Idempotency-Key`, expects HTTP 202 and limits batches to 1000 matches and 2 MB. Failed deliveries raise an ElastAlert error; configure retries and monitoring in ElastAlert.

The web proxy forwards `/api/*`, not `/webhook/incident`. Use the private API route supplied by the rule. Remote senders need a separately configured restricted HTTPS ingress. Adapter tests mock HTTP calls.
