#!/usr/bin/env bash
set -e

echo "Splitting"
./manage.py clean_data --file catalog/core/migrations/clean_data/sponsor.split
./manage.py clean_data --file catalog/core/migrations/clean_data/platform.split

echo "Merging"
./manage.py clean_data --file catalog/core/migrations/clean_data/sponsor.merge
./manage.py clean_data --file catalog/core/migrations/clean_data/platform.merge
./manage.py clean_data --file catalog/core/migrations/clean_data/model_documentation.merge

echo "Deleting"
./manage.py clean_data --file catalog/core/migrations/clean_data/sponsor.delete
./manage.py clean_data --file catalog/core/migrations/clean_data/platform.delete
./manage.py clean_data --file catalog/core/migrations/clean_data/model_documentation.delete
