#!/usr/bin/env bash
# Start a throwaway PostgreSQL for the test suite on 127.0.0.1:54331.
# Stop it with: docker stop ofl-test
set -euo pipefail

name=ofl-test
if ! docker ps --format '{{.Names}}' | grep -qx "$name"; then
  docker run -d --rm --name "$name" \
    -e POSTGRES_USER=fi -e POSTGRES_PASSWORD=fi -e POSTGRES_DB=ofl_test \
    -p 127.0.0.1:54331:5432 postgres:17 >/dev/null
fi
for _ in $(seq 1 30); do
  docker exec "$name" pg_isready -U fi -d ofl_test >/dev/null 2>&1 && break
  sleep 1
done
echo "OFL_TEST_DATABASE_URL=postgresql://fi:fi@127.0.0.1:54331/ofl_test"
