FROM comses/base:1.0.1

RUN apt-get update && apt-get install -q -y \
    libxml2-dev \
    python3-dev \
    python3-pip \
    curl \
    git \
    ssmtp \
    wget \
    && echo "deb http://apt.postgresql.org/pub/repos/apt/ xenial-pgdg main" | tee /etc/apt/sources.list.d/postgresql.list \
    && wget -q -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - \
    && apt-get update \
    && apt-get install -q -y postgresql-9.6 postgresql-client-9.6 libpq-dev

ENV PYTHONUNBUFFERED 1
COPY citation /code/citation

# copy cron script to be run daily
COPY deploy/cron/daily_catalog_tasks /etc/cron.daily/
COPY requirements.txt /tmp/
# Set execute bit on the cron script and install pip dependencies
RUN chmod +x /etc/cron.daily/daily_catalog_tasks \
    && pip3 install -q -r /tmp/requirements.txt

COPY deploy/mail/ssmtp.conf /etc/ssmtp/ssmtp.conf

WORKDIR /code
CMD ["/code/deploy/docker/dev.sh"]
