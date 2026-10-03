# HelioVolt Deployment Runbook — Cloud Platform v4.1

**Doc ID:** HV-ENG-005 | **Version:** 4.1.7 | **Owner:** Platform Team (#platform) | **Last Updated:** Feb 25, 2026

## 1. Environments
- dev: `dev.heliovolt.fake` (auto-deploy main branch)
- staging: `staging.heliovolt.fake` (manual promote, mirrors prod data anonymized)
- prod US: `app.heliovolt.fake` (AWS us-east-1, ECS Fargate, RDS Postgres 15.4)
- prod EU: `app-eu.heliovolt.fake` (AWS eu-central-1, isolated VPC vpc-eu-042)

Deploy freeze: Fridays 3pm CT → Mondays 9am CT. No deploys during SOC 2 audit June 1-30, 2026.

## 2. Standard Deploy
```bash
git tag v4.1.8
gh workflow run deploy.yml --ref v4.1.8 --field env=staging
# smoke test
curl https://staging.heliovolt.fake/healthz # expect {"status":"OK","version":"4.1.8"}
# promote
gh workflow run promote.yml --field version=4.1.8 --field env=prod-us
```

Canary: 5% traffic 15 min → 50% 30 min → 100%. Rollback command: `gh workflow run rollback.yml --field env=prod-us --field to=v4.1.7`. Rollback SLA 15 min.

## 3. Secrets & Config
Prod secrets in AWS Secrets Manager `hv-prod/*`. Required vars: `MQTT_BROKER=mqtt.heliovolt.fake:8883`, `DB_URL`, `OKTA_CLIENT_ID`. Never commit `.env`. Rotate API keys every 90 days.

## 4. Monitoring
- Datadog dashboard: `HelioVolt Prod Overview`. Alerts to PagerDuty + Slack #eng-alerts.
- SEV1 (down >5 min, error rate >5%): page on-call immediately. SEV2 (latency p99 >800ms): ticket within 4h.
- Log retention: CloudWatch 90 days, S3 `hv-prod-logs` 13 months.

## 5. Database Migrations
Run `alembic upgrade head` on staging first, snapshot RDS (`hv-prod-pg-01`) before prod. Downtime migrations need 48h notice + CEO approval if >2 min.

## 6. Contacts
On-call: PagerDuty schedule `HV-Platform`. Escalation: L1 on-call → Daniel Okoro (CTO) → Maya Rangan. Status page: status.heliovolt.fake.
