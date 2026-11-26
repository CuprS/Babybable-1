#!/usr/bin/env bash
# Nightly backup (run by cron from setup.sh, and before every update.sh):
#  - the database, as a compressed mongodump archive
#  - uploaded files, when STORAGE_BACKEND=local
# Kept in /var/backups/babybabel for BACKUP_KEEP_DAYS days, and copied to BACKUP_S3_BUCKET if set.
set -euo pipefail
cd "$(dirname "$0")"

# Read single settings from .env as plain text (it isn't shell code: values like
# "Babybabel <hello@…>" would break `source`). Strips inline "# comments" and quotes.
env_get() {
  sed -n "s/^$1=//p" .env | tail -n1 | sed 's/[[:space:]]\+#.*$//; s/^"\(.*\)"$/\1/; s/[[:space:]]*$//'
}
STORAGE_BACKEND="$(env_get STORAGE_BACKEND)"
BACKUP_S3_BUCKET="$(env_get BACKUP_S3_BUCKET)"
BACKUP_KEEP_DAYS="$(env_get BACKUP_KEEP_DAYS)"
S3_ENDPOINT_URL="$(env_get S3_ENDPOINT_URL)"
S3_REGION="$(env_get S3_REGION)"
export AWS_ACCESS_KEY_ID="$(env_get AWS_ACCESS_KEY_ID)"
export AWS_SECRET_ACCESS_KEY="$(env_get AWS_SECRET_ACCESS_KEY)"
DEST=/var/backups/babybabel
STAMP="$(date -u +%Y%m%d-%H%M%S)"
KEEP="${BACKUP_KEEP_DAYS:-14}"
mkdir -p "$DEST"
chmod 700 "$DEST"

echo "[$STAMP] database"
# The root password is read inside the container, so it never appears in the host's process list.
docker compose exec -T mongo sh -c \
  'mongodump --username root --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --db babybabel --archive --gzip' \
  > "$DEST/db-$STAMP.archive.gz"

FILES=("$DEST/db-$STAMP.archive.gz")
if [[ "${STORAGE_BACKEND:-local}" == "local" ]]; then
  echo "[$STAMP] uploaded files"
  docker run --rm -v babybabel_uploads:/data:ro -v "$DEST":/out alpine \
    tar -czf "/out/uploads-$STAMP.tar.gz" -C /data .
  FILES+=("$DEST/uploads-$STAMP.tar.gz")
fi

if [[ -n "${BACKUP_S3_BUCKET:-}" ]]; then
  echo "[$STAMP] copying off-site to s3://$BACKUP_S3_BUCKET"
  for f in "${FILES[@]}"; do
    docker run --rm -v "$DEST":/backups:ro \
      -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION="${S3_REGION:-fsn1}" \
      amazon/aws-cli --endpoint-url "$S3_ENDPOINT_URL" \
      s3 cp "/backups/$(basename "$f")" "s3://$BACKUP_S3_BUCKET/$(basename "$f")" --only-show-errors
  done
fi

find "$DEST" -type f -mtime +"$KEEP" -delete
echo "[$STAMP] done: ${FILES[*]}"
