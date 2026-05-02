#!/usr/bin/env bash
# ============================================================================
# Create the S3 bucket for company documents.
#
# What this script does:
#   1. Creates the bucket (region-aware — bucket creation differs in us-east-1).
#   2. Blocks all public access (defense in depth — we use presigned URLs).
#   3. Enables default encryption (SSE-S3, AES-256).
#   4. Enables versioning (so an accidental DELETE is recoverable).
#   5. Adds a lifecycle rule to clean up multipart-upload junk after 7 days.
#
# Prereqs:
#   - aws CLI v2 configured with credentials that can create buckets.
#   - BUCKET and REGION env vars (see defaults below).
# ============================================================================
set -euo pipefail

BUCKET="${BUCKET:-company-ai-docs}"
REGION="${REGION:-ap-south-1}"

echo "==> Creating bucket s3://${BUCKET} in ${REGION}"

# us-east-1 is the only region where you must NOT pass --create-bucket-configuration.
if [ "$REGION" = "us-east-1" ]; then
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
else
  aws s3api create-bucket \
    --bucket "$BUCKET" \
    --region "$REGION" \
    --create-bucket-configuration "LocationConstraint=$REGION"
fi

echo "==> Blocking public access"
aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo "==> Enabling default encryption (SSE-S3)"
aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": { "SSEAlgorithm": "AES256" }
    }]
  }'

echo "==> Enabling versioning"
aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration "Status=Enabled"

echo "==> Lifecycle rule: abort incomplete multipart uploads after 7 days"
aws s3api put-bucket-lifecycle-configuration \
  --bucket "$BUCKET" \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "abort-incomplete-multipart",
      "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 7 }
    }]
  }'

echo "==> Done. Set S3_BUCKET_DOCS=${BUCKET} in your .env"