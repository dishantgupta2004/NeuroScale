#!/usr/bin/env bash
# ============================================================================
# SES verification.
#
# IMPORTANT: New AWS accounts start in the SES SANDBOX:
#   - You can only send TO and FROM verified email addresses.
#   - Max 200 emails/day, 1 email/second.
#   - To exit the sandbox, request production access in the SES console
#     (it takes 24h and asks about your bounce/complaint handling plan).
#
# What this script does:
#   1. Verifies a sender email/domain.
#   2. Verifies up to N recipient emails (sandbox testing only).
#   3. Prints the next steps.
#
# Each verified address gets an email from AWS — the owner must click the
# link before SES will send to/from that address.
# ============================================================================
set -euo pipefail

REGION="${REGION:-ap-south-1}"
SENDER="${SENDER:-noreply@yourdomain.com}"

echo "==> Verifying sender: ${SENDER}"
aws ses verify-email-identity --email-address "$SENDER" --region "$REGION"
echo "    Check the inbox for ${SENDER} and click the AWS verification link."

# Optional recipients (for sandbox testing). Pass as space-separated list.
if [ -n "${RECIPIENTS:-}" ]; then
  for addr in $RECIPIENTS; do
    echo "==> Verifying recipient: $addr"
    aws ses verify-email-identity --email-address "$addr" --region "$REGION"
  done
fi

echo ""
echo "==> Verification request(s) sent. Pending until each owner clicks the link."
echo "    Check status:"
echo "       aws ses list-verified-email-addresses --region $REGION"
echo ""
echo "==> Next: when ready for production, request sandbox exit:"
echo "    https://console.aws.amazon.com/ses/home?region=${REGION}#/account"
echo ""
echo "==> Add to your .env:"
echo "    SES_SENDER_EMAIL=${SENDER}"