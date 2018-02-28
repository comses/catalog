FROM comses/base:1.1.0

ARG RUN_SCRIPT=./deploy/docker/dev.sh
ARG UBUNTU_MIRROR=mirror.math.princeton.edu/pub

RUN sed -i "s|archive.ubuntu.com|${UBUNTU_MIRROR}|" /etc/apt/sources.list \
    && echo "deb http://apt.postgresql.org/pub/repos/apt/ xenial-pgdg main" | tee /etc/apt/sources.list.d/postgresql.list \
    && apt-get update && apt-get install -q -y \
    curl \
    git \
    libxml2-dev \
    python3-dev \
    python3-pip \
    ssmtp \
    wget \
    && wget -q -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - \
    && apt-get update && apt-get install -q -y postgresql-9.6 postgresql-client-9.6 libpq-dev autopostgresqlbackup \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3 1000 \
    && mkdir -p /etc/service/django \
    && touch /etc/service/django/run /etc/postgresql-backup-pre \
    && chmod a+x /etc/service/django/run /etc/postgresql-backup-pre \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY ./deploy/db/autopostgresqlbackup.conf /etc/default/autopostgresqlbackup
COPY ./deploy/db/postgresql-backup-pre /etc/
COPY ${RUN_SCRIPT} /etc/service/django/run

# copy cron script to be run daily
COPY deploy/cron/daily_catalog_tasks /etc/cron.daily/
COPY requirements.txt citation /tmp/
# Set execute bit on the cron script and install pip dependencies
RUN chmod +x /etc/cron.daily/daily_catalog_tasks \
    && pip3 install -r /tmp/requirements.txt

COPY deploy/mail/ssmtp.conf /etc/ssmtp/ssmtp.conf
WORKDIR /code
COPY . /code
CMD ["/sbin/my_init"]
