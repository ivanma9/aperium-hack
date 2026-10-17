#!/bin/sh
# Separate database for the test suite (tests reset it). Runs once, when the volume is created.
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE DATABASE aperium_test OWNER \"$POSTGRES_USER\""
