#!/usr/bin/env bash
# ============================================================================
# Create an RDS PostgreSQL instance for the app.
#
# What this script does:
#   1. Creates a security group that allows Postgres (5432) from your EC2 SG.
#   2. Creates a db.t3.micro instance (free-tier eligible).
#   3. Enables encryption at rest.
#   4. Sets a 7-day automated backup window.
#
# This script is INTERACTIVE — it asks for the master password rather than
# accepting it as a flag (passwords in shell history are bad).
#
# Prereqs:
#   - aws CLI v2 configured.
#   - You have an EC2 security group ID handy (the app's SG).
#     If not, create the EC2 instance first via setup_ec2.sh.
# ============================================================================
set -euo pipefail

DB_INSTANCE_ID="${DB_INSTANCE_ID:-company-ai-db}"
DB_NAME="${DB_NAME:-aiassistant}"
DB_USER="${DB_USER:-appuser}"
REGION="${REGION:-ap-south-1}"
APP_SG_ID="${APP_SG_ID:-}"   # the SG attached to your EC2 instance

if [ -z "$APP_SG_ID" ]; then
  echo "ERROR: APP_SG_ID env var must be set to your EC2 security group ID."
  echo "Run setup_ec2.sh first, or pass APP_SG_ID=sg-xxxxx ./setup_rds.sh"
  exit 1
fi

read -rsp "Enter the new RDS master password (min 8 chars): " DB_PASS
echo

# ---------------------------------------------------------------------------
# 1. Create a security group for the DB that only allows traffic from the app
# ---------------------------------------------------------------------------
echo "==> Creating DB security group"
DB_SG_ID=$(aws ec2 create-security-group \
  --group-name "${DB_INSTANCE_ID}-sg" \
  --description "Postgres access from app SG only" \
  --region "$REGION" \
  --query "GroupId" --output text)

# Allow 5432 from the app SG (NOT 0.0.0.0/0 — never expose Postgres publicly).
aws ec2 authorize-security-group-ingress \
  --group-id "$DB_SG_ID" \
  --protocol tcp --port 5432 \
  --source-group "$APP_SG_ID" \
  --region "$REGION"

echo "    DB SG: $DB_SG_ID"

# ---------------------------------------------------------------------------
# 2. Create the RDS instance
# ---------------------------------------------------------------------------
echo "==> Creating RDS instance ${DB_INSTANCE_ID} (this takes ~5 minutes)"
aws rds create-db-instance \
  --db-instance-identifier "$DB_INSTANCE_ID" \
  --db-instance-class db.t3.micro \
  --engine postgres \
  --engine-version 16.3 \
  --allocated-storage 20 \
  --storage-type gp3 \
  --storage-encrypted \
  --master-username "$DB_USER" \
  --master-user-password "$DB_PASS" \
  --db-name "$DB_NAME" \
  --vpc-security-group-ids "$DB_SG_ID" \
  --backup-retention-period 7 \
  --no-publicly-accessible \
  --region "$REGION"

echo "==> Waiting for instance to be available..."
aws rds wait db-instance-available \
  --db-instance-identifier "$DB_INSTANCE_ID" \
  --region "$REGION"

# ---------------------------------------------------------------------------
# 3. Print the endpoint for the .env file
# ---------------------------------------------------------------------------
ENDPOINT=$(aws rds describe-db-instances \
  --db-instance-identifier "$DB_INSTANCE_ID" \
  --region "$REGION" \
  --query "DBInstances[0].Endpoint.Address" --output text)

echo ""
echo "==> RDS ready."
echo "    Endpoint: ${ENDPOINT}"
echo ""
echo "Add this to your .env (escape the password if it has special chars):"
echo "DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASS}@${ENDPOINT}:5432/${DB_NAME}"