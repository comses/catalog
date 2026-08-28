FROM python:3.12-slim AS base

ARG RUN_SCRIPT=./deploy/docker/dev.sh

# OS-level operational tooling preserved from the legacy Focal image:
# Postgres backup client + pre-backup hook, mail relay, Postgres client
# tools, and git/curl for ops. The legacy build toolchain (libpq-dev,
# libxml2-dev, python3-dev, python3-pip, python3-setuptools) is no longer
# needed: the locked uv environment installs prebuilt wheels only.
RUN apt-get update \
    && apt-get install --no-install-recommends -q -y \
        autopostgresqlbackup \
        curl \
        git \
        postgresql-client \
        ssmtp \
    && rm -rf /var/lib/apt/lists/*

# Reproducible dependency management, pinned to the uv version that
# produces and validates the root uv.lock.
RUN pip install --no-cache-dir "uv==0.10.10"

WORKDIR /code

# The root project resolves "citation" as an editable path dependency, so
# the citation checkout must be in place before the locked sync can build
# and install it.
COPY citation /code/citation
COPY pyproject.toml uv.lock /code/

# Install the locked production dependencies (no dev dependency group).
# The venv lives outside /code so the dev `.: /code` bind mount can never
# shadow or clobber it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv sync --locked --no-dev
ENV PATH="/opt/venv/bin:$PATH"

COPY deploy/mail/ssmtp.conf /etc/ssmtp/ssmtp.conf
# copy cron script to be run daily
COPY deploy/cron/daily_catalog_tasks /etc/cron.daily/
COPY deploy/cron/monthly_catalog_tasks /etc/cron.monthly/
# Gunicorn socket dir (staging/prod also mount a named volume at this path)
RUN chmod +x /etc/cron.daily/daily_catalog_tasks \
    && chmod +x /etc/cron.monthly/monthly_catalog_tasks \
    && mkdir -p /catalog/socket /etc/service/django

COPY . /code

COPY deploy/db/autopostgresqlbackup.conf /etc/default/autopostgresqlbackup
COPY deploy/db/postgresql-backup-pre /etc/
RUN chmod a+x /etc/postgresql-backup-pre

COPY ${RUN_SCRIPT} /etc/service/django/run
RUN chmod a+x /etc/service/django/run

# The legacy image started this script through runit (/sbin/my_init);
# running the same script directly preserves the foreground service
# behavior (dev.sh/prod.sh both exec their server process).
CMD ["/etc/service/django/run"]
