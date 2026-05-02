#!/usr/bin/env bash
# ============================================================================
# Create the EC2 instance that runs the FastAPI app + FAISS + Ollama.
#
# Sizing notes
# ------------
# t3.micro (free tier): TOO SMALL. Ollama needs >= 8GB RAM for llama3.1:8b.
# t3.medium (4GB):      OK with smaller model (llama3.2:3b) or Groq-only.
# t3.large (8GB):       Recommended baseline for llama3.1:8b + FAISS.
# t3.xlarge (16GB):     Comfortable headroom + larger FAISS indexes.
#
# We default to t3.large. Adjust INSTANCE_TYPE for your budget.
#
# What this script does:
#   1. Creates a security group allowing SSH (22) + HTTP (80) + HTTPS (443).
#   2. Creates an IAM role + instance profile from iam_policy.json.
#   3. Launches an Ubuntu 24.04 LTS instance with the role attached.
#   4. Prints the public IP for SSH.
#
# Prereqs:
#   - aws CLI v2.
#   - An EC2 key pair you can SSH with (KEY_NAME).
# ============================================================================
set -euo pipefail

REGION="${REGION:-ap-south-1}"
INSTANCE_NAME="${INSTANCE_NAME:-company-ai-app}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.large}"
KEY_NAME="${KEY_NAME:-}"           # your existing EC2 key pair name
ROLE_NAME="${ROLE_NAME:-CompanyAIAppRole}"
PROFILE_NAME="${PROFILE_NAME:-CompanyAIAppProfile}"
POLICY_FILE="$(dirname "$0")/iam_policy.json"

if [ -z "$KEY_NAME" ]; then
  echo "ERROR: KEY_NAME env var must be set to your EC2 key pair name."
  exit 1
fi

# ---------------------------------------------------------------------------
# 1. Find the latest Ubuntu 24.04 LTS AMI for the region
# ---------------------------------------------------------------------------
echo "==> Resolving latest Ubuntu 24.04 LTS AMI for ${REGION}"
AMI_ID=$(aws ec2 describe-images \
  --owners 099720109477 \
  --filters \
    "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" \
    "Name=state,Values=available" \
  --query "sort_by(Images, &CreationDate)[-1].ImageId" \
  --output text --region "$REGION")
echo "    AMI: $AMI_ID"

# ---------------------------------------------------------------------------
# 2. Security group
# ---------------------------------------------------------------------------
echo "==> Creating security group ${INSTANCE_NAME}-sg"
APP_SG_ID=$(aws ec2 create-security-group \
  --group-name "${INSTANCE_NAME}-sg" \
  --description "App: SSH + HTTP + HTTPS" \
  --region "$REGION" \
  --query "GroupId" --output text)

# SSH — restrict to your IP in production. For setup we open 22 widely;
# you SHOULD tighten it after first login:
#   aws ec2 revoke-security-group-ingress --group-id $APP_SG_ID --protocol tcp --port 22 --cidr 0.0.0.0/0
#   aws ec2 authorize-security-group-ingress --group-id $APP_SG_ID --protocol tcp --port 22 --cidr YOUR_IP/32
aws ec2 authorize-security-group-ingress --group-id "$APP_SG_ID" --protocol tcp --port 22  --cidr 0.0.0.0/0 --region "$REGION"
aws ec2 authorize-security-group-ingress --group-id "$APP_SG_ID" --protocol tcp --port 80  --cidr 0.0.0.0/0 --region "$REGION"
aws ec2 authorize-security-group-ingress --group-id "$APP_SG_ID" --protocol tcp --port 443 --cidr 0.0.0.0/0 --region "$REGION"

echo "    SG: $APP_SG_ID"

# ---------------------------------------------------------------------------
# 3. IAM role + instance profile (so the app can talk to S3/SES without keys)
# ---------------------------------------------------------------------------
echo "==> Creating IAM role ${ROLE_NAME}"

# Trust policy — only EC2 may assume this role.
TRUST_DOC='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "ec2.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}'

aws iam create-role \
  --role-name "$ROLE_NAME" \
  --assume-role-policy-document "$TRUST_DOC" \
  >/dev/null

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name CompanyAIAppPolicy \
  --policy-document "file://${POLICY_FILE}"

aws iam create-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null
aws iam add-role-to-instance-profile \
  --instance-profile-name "$PROFILE_NAME" \
  --role-name "$ROLE_NAME"

# Instance profiles take a few seconds to propagate after creation.
echo "    Waiting 10s for IAM propagation..."
sleep 10

# ---------------------------------------------------------------------------
# 4. User-data script — installs Docker on first boot
# ---------------------------------------------------------------------------
USER_DATA=$(cat <<'EOF'
#!/bin/bash
set -e
apt-get update
apt-get install -y ca-certificates curl gnupg git

# Docker
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker ubuntu

# Ollama
curl -fsSL https://ollama.com/install.sh | sh
systemctl enable ollama
systemctl start ollama
# Pre-pull the model so first agent call is instant.
sudo -u ubuntu ollama pull llama3.1:8b || true
EOF
)

# ---------------------------------------------------------------------------
# 5. Launch the instance
# ---------------------------------------------------------------------------
echo "==> Launching ${INSTANCE_TYPE} instance"
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type "$INSTANCE_TYPE" \
  --key-name "$KEY_NAME" \
  --security-group-ids "$APP_SG_ID" \
  --iam-instance-profile "Name=${PROFILE_NAME}" \
  --user-data "$USER_DATA" \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":50,"VolumeType":"gp3","Encrypted":true}}]' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${INSTANCE_NAME}}]" \
  --region "$REGION" \
  --query "Instances[0].InstanceId" --output text)

echo "    Instance: $INSTANCE_ID"
echo "==> Waiting for instance to be running..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"

PUBLIC_IP=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text)

echo ""
echo "==========================================================="
echo "EC2 instance ready."
echo "  Instance ID : $INSTANCE_ID"
echo "  Public IP   : $PUBLIC_IP"
echo "  Security SG : $APP_SG_ID    <-- pass this as APP_SG_ID to setup_rds.sh"
echo ""
echo "SSH in once cloud-init finishes (~3 min):"
echo "  ssh -i ~/.ssh/${KEY_NAME}.pem ubuntu@${PUBLIC_IP}"
echo "==========================================================="