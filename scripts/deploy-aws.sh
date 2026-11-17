#!/usr/bin/env bash
# Deploy the current commit to AWS (after `tofu apply` created the infrastructure).
#
#   ./scripts/deploy-aws.sh            build, push, migrate, roll out API+worker, upload frontend
#   DRY_RUN=1 ./scripts/deploy-aws.sh  print what would happen, change nothing
#
# Steps
#   1. Build the API image for ARM64 (Graviton) and push it to ECR, tagged with the git SHA.
#   2. Register new task-definition revisions that use that image.
#   3. Run the one-off `migrate` task and STOP if it fails (old version keeps serving).
#   4. Point the api + worker services at the new revisions; ECS rolls tasks over with
#      zero downtime and rolls back automatically if the new tasks are unhealthy.
#   5. Build the React app and upload it to S3 (hashed assets: 1-year cache; index.html:
#      no-cache), then invalidate index.html in CloudFront.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF="$ROOT/infra/terraform"
TOFU="$(command -v tofu || command -v terraform)"
run() { if [[ -n "${DRY_RUN:-}" ]]; then echo "DRY-RUN: $*"; else "$@"; fi; }
out() { "$TOFU" -chdir="$TF" output -raw "$1"; }
step() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }

git -C "$ROOT" diff --quiet || { echo "Commit or stash your changes first (the image is tagged with the commit)."; exit 1; }
TAG="$(git -C "$ROOT" rev-parse --short HEAD)"
REGION="$(out region)"
REPO="$(out ecr_repository_url)"
CLUSTER="$(out ecs_cluster)"
BUCKET="$(out web_bucket)"
DIST="$(out cloudfront_distribution_id)"
SUBNETS="$("$TOFU" -chdir="$TF" output -json app_subnets | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)))')"
SG="$(out app_security_group)"
export AWS_REGION="$REGION"

step "1/5 Build and push $REPO:$TAG (linux/arm64)"
run aws ecr get-login-password | run docker login --username AWS --password-stdin "${REPO%%/*}"
run docker buildx build --platform linux/arm64 -t "$REPO:$TAG" --push "$ROOT/backend"

# Copy the current task definition, swap the image, register it as a new revision.
new_revision() {
  local family="$1"
  aws ecs describe-task-definition --task-definition "$family" --query taskDefinition --output json \
  | python3 -c '
import json, sys
td = json.load(sys.stdin)
for c in td["containerDefinitions"]:
    c["image"] = sys.argv[1]
keep = ["family", "taskRoleArn", "executionRoleArn", "networkMode", "containerDefinitions",
        "requiresCompatibilities", "cpu", "memory", "runtimePlatform"]
print(json.dumps({k: td[k] for k in keep if k in td}))' "$REPO:$TAG" > "/tmp/td-$family.json"
  aws ecs register-task-definition --cli-input-json "file:///tmp/td-$family.json" \
    --query taskDefinition.taskDefinitionArn --output text
}

step "2/5 Register task definitions"
if [[ -n "${DRY_RUN:-}" ]]; then
  echo "DRY-RUN: register new revisions of mealconnect-prod-{migrate,api,worker} with image $REPO:$TAG"
else
  MIGRATE_TD="$(new_revision mealconnect-prod-migrate)"
  API_TD="$(new_revision mealconnect-prod-api)"
  WORKER_TD="$(new_revision mealconnect-prod-worker)"
  echo "$MIGRATE_TD"; echo "$API_TD"; echo "$WORKER_TD"
fi

step "3/5 Run database migrations"
if [[ -z "${DRY_RUN:-}" ]]; then
  TASK="$(aws ecs run-task --cluster "$CLUSTER" --launch-type FARGATE --task-definition "$MIGRATE_TD" \
    --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=ENABLED}" \
    --query 'tasks[0].taskArn' --output text)"
  echo "migration task: $TASK"
  aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK"
  CODE="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK" --query 'tasks[0].containers[0].exitCode' --output text)"
  if [[ "$CODE" != "0" ]]; then
    echo "Migration failed (exit $CODE). Nothing was rolled out. Logs: /ecs/mealconnect-prod/migrate"; exit 1
  fi
  echo "migrations applied"
else
  echo "DRY-RUN: aws ecs run-task ... migrate, wait, require exit code 0"
fi

step "4/5 Roll out API and worker"
run aws ecs update-service --cluster "$CLUSTER" --service api --task-definition "${API_TD:-api}" --query service.serviceName --output text
run aws ecs update-service --cluster "$CLUSTER" --service worker --task-definition "${WORKER_TD:-worker}" --query service.serviceName --output text
run aws ecs wait services-stable --cluster "$CLUSTER" --services api worker
echo "services stable"

step "5/5 Upload frontend"
(cd "$ROOT/frontend" && run npm ci --no-audit --no-fund && run npm run build)
run aws s3 sync "$ROOT/frontend/dist/assets" "s3://$BUCKET/assets" \
  --cache-control "public, max-age=31536000, immutable"
run aws s3 sync "$ROOT/frontend/dist" "s3://$BUCKET" --exclude "assets/*" --delete \
  --cache-control "no-cache"
run aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/index.html" "/" \
  --query Invalidation.Id --output text

printf '\n\033[1;32mDeployed %s -> %s\033[0m\n' "$TAG" "$(out site_url)"
