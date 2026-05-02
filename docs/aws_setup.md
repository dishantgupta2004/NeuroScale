# AWS Deployment Guide

End-to-end instructions for getting the Company AI Assistant running on AWS.

> **Time estimate:** ~30 minutes the first time, ~10 minutes if you've done it before.

---

## Prerequisites

1. **AWS account** with billing enabled.
2. **AWS CLI v2** installed and configured: `aws configure`.
3. **An EC2 key pair** in your target region. Create one in the EC2 console if needed and save the `.pem` file with `chmod 400`.
4. **A domain (optional but recommended)** for SES — verifying a whole domain is more useful than a single email address.
5. **Decide on a region.** The scripts default to `ap-south-1` (Mumbai). Change `REGION=...` if you want a different one.

---

## Architecture refresher

```
Internet
   │
   ▼
EC2 (t3.large, Ubuntu 24.04)
   ├─ FastAPI (uvicorn :8000)
   ├─ FAISS index files (local disk)
   ├─ Ollama (:11434, local)
   └─ IAM Instance Profile  ──►  S3 + SES (no AWS keys in env)
        │
        ▼
       RDS PostgreSQL (private subnet, only accessible from EC2 SG)
```

The EC2 instance assumes an **IAM role** which grants S3 + SES permissions. This means no `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env vars in production — `aioboto3` picks the credentials up automatically from the instance metadata service.

---

## Step 1 — Create the S3 bucket

```bash
cd infra/aws
chmod +x setup_s3.sh

BUCKET=company-ai-docs-yourname \
REGION=ap-south-1 \
./setup_s3.sh
```

S3 bucket names are globally unique — pick something with your initials or company.

After this runs:
- Bucket exists, private, encrypted, versioned.
- Add to your `.env`: `S3_BUCKET_DOCS=company-ai-docs-yourname`

---

## Step 2 — Launch the EC2 instance

This script also creates the IAM role + security group, so it must run **before** RDS.

```bash
chmod +x setup_ec2.sh

KEY_NAME=your-keypair-name \
REGION=ap-south-1 \
INSTANCE_TYPE=t3.large \
./setup_ec2.sh
```

Output will include:
- **Instance ID** — keep this.
- **Public IP** — for SSH.
- **Security Group ID** (`sg-xxxxx`) — pass this to the RDS script.

Wait ~3 minutes for cloud-init to finish (Docker + Ollama install + model pull).

Then SSH in to verify:
```bash
ssh -i ~/.ssh/your-keypair-name.pem ubuntu@<PUBLIC_IP>
docker --version       # should print Docker 27.x
ollama list            # should show llama3.1:8b
```

> **Tighten SSH access now.** The launch script opens port 22 to `0.0.0.0/0` for convenience. Lock it down:
> ```bash
> aws ec2 revoke-security-group-ingress --group-id sg-xxx --protocol tcp --port 22 --cidr 0.0.0.0/0
> aws ec2 authorize-security-group-ingress --group-id sg-xxx --protocol tcp --port 22 --cidr $(curl -s ifconfig.me)/32
> ```

---

## Step 3 — Create the RDS PostgreSQL instance

```bash
APP_SG_ID=sg-xxxxx \
DB_INSTANCE_ID=company-ai-db \
REGION=ap-south-1 \
./setup_rds.sh
```

The script will prompt for a master password (not echoed to your shell history).

Output will include the RDS endpoint hostname. Use it to build the `DATABASE_URL`:

```
DATABASE_URL=postgresql+asyncpg://appuser:YOUR_PASS@company-ai-db.xxxxx.ap-south-1.rds.amazonaws.com:5432/aiassistant
```

> **The DB is private** — it has no public IP. Only the app's security group can connect on port 5432. To run migrations from your laptop, either:
> 1. Use SSH tunneling through the EC2 box: `ssh -L 5432:<rds-endpoint>:5432 ubuntu@<ec2-ip>`
> 2. Or run migrations on EC2 itself: `ssh ubuntu@<ec2-ip>` then `alembic upgrade head`.

Provisioning takes 5–10 minutes. The script polls until ready.

---

## Step 4 — Verify SES sender identity

```bash
SENDER=noreply@yourdomain.com \
RECIPIENTS="me@gmail.com prospect@example.com" \
REGION=ap-south-1 \
./setup_ses.sh
```

Each verified address gets an email from AWS. Click the link in each one.

> **You're in the SES sandbox.** Until you request production access (24h turnaround in the AWS console), you can only send to/from verified addresses, max 200/day. For testing, that's plenty.

Add to `.env`:
```
SES_SENDER_EMAIL=noreply@yourdomain.com
```

---

## Step 5 — Deploy the app to EC2

SSH in and pull the code:

```bash
ssh -i ~/.ssh/your-keypair.pem ubuntu@<EC2_PUBLIC_IP>

# Clone the repo
git clone https://github.com/your-org/company-ai-assistant.git
cd company-ai-assistant/backend

# Build & run with Docker (Dockerfile + compose come in Phase 8)
# For now, run uvicorn directly:
sudo apt-get install -y python3.12-venv python3-pip
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy and edit env
cp .env.example .env
nano .env
```

Fill in `.env` on the EC2 box:
```
APP_ENV=production
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_urlsafe(48))">

DATABASE_URL=postgresql+asyncpg://appuser:PASS@<RDS_ENDPOINT>:5432/aiassistant

GROQ_API_KEY=gsk_your_real_key

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b

# DO NOT set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in production.
# The instance role provides credentials automatically.
AWS_REGION=ap-south-1
S3_BUCKET_DOCS=company-ai-docs-yourname
SES_SENDER_EMAIL=noreply@yourdomain.com
```

Start the app:
```bash
# For testing, foreground:
uvicorn app.main:app --host 0.0.0.0 --port 8000

# For production, use a systemd service or supervisord (or Docker — Phase 8).
```

Smoke test from your laptop:
```bash
curl http://<EC2_PUBLIC_IP>:8000/health
# {"status":"ok","env":"production"}

curl http://<EC2_PUBLIC_IP>:8000/health/llm
# Should show groq + ollama provider statuses
```

> **Don't expose 8000 directly.** In Phase 8 we'll put nginx in front of it for TLS termination + rate limiting.

---

## Step 6 — Verify the full pipeline

From your laptop:

```bash
HOST=http://<EC2_PUBLIC_IP>:8000

# 1. Sign up
TOKEN=$(curl -s -X POST $HOST/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"founder@acme.com","password":"super-secret-123","company_name":"Acme"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Upload a doc — this hits S3 + FAISS
curl -X POST $HOST/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/your-about.pdf"

# Check S3:
aws s3 ls s3://company-ai-docs-yourname/companies/ --recursive

# 3. Ask the brain
curl -X POST $HOST/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"What does Acme do?"}'

# 4. Generate content
curl -X POST $HOST/generate-content \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task":"Announce our launch on LinkedIn","content_type":"linkedin_post"}'

# 5. Send a real email (must be to a verified address while in sandbox!)
curl -X POST $HOST/send-email \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to_address":"verified@yourdomain.com","generation_task":"Friendly intro email"}'
# Returns email_id; then approve to actually send:
curl -X POST $HOST/approve-email \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email_id":"<id_from_above>","approve":true}'

# Check your inbox.
```

---

## Cost expectations (free tier + light use)

| Service | Spec | Approx monthly |
|---|---|---|
| EC2 t3.large | 24/7 (Mumbai) | ~$60 |
| RDS db.t3.micro | 24/7 (free tier 12 mo) | $0 → ~$15 |
| S3 | <5GB docs | <$0.50 |
| SES | 1000 emails | $0.10 |
| Data transfer | typical | <$5 |
| **Total** | | **~$15 (year 1) / ~$80** |

If you don't need llama3.1:8b locally and Groq is enough, drop to `t3.medium` and save ~$30/mo.

---

## Troubleshooting

**"Could not connect to RDS"** — confirm the DB security group allows port 5432 from the app SG, not from `0.0.0.0/0`. Also confirm `--no-publicly-accessible` was set; the DB has no public DNS.

**"Access Denied" on S3 or SES** — the EC2 role policy didn't propagate. Verify with:
```bash
aws sts get-caller-identity   # run this ON the EC2 box
# Should print the role ARN, not your laptop's IAM user.
```

**SES `MessageRejected: Email address is not verified`** — you're in the sandbox. Either verify the recipient or request production access in the SES console.

**Ollama OOM-killed** — your instance is too small. Either upgrade to t3.xlarge or use a smaller model (`OLLAMA_MODEL=llama3.2:3b`).