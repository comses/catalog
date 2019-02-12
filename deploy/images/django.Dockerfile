FROM comses/base:1.2.0 as base

ARG RUN_SCRIPT=./deploy/docker/dev.sh
ARG UBUNTU_MIRROR=mirror.math.princeton.edu/pub

RUN sed -i "s|archive.ubuntu.com|${UBUNTU_MIRROR}|" /etc/apt/sources.list \
    && apt-get update && apt-get install --no-install-recommends -q -y \
    autopostgresqlbackup \
    curl \
    git \
    libxml2-dev \
    postgresql-client \
    python3-dev \
    python3-pip \
    python3-setuptools \
    ssmtp \
    wget \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3 1000 \
    && mkdir -p /etc/service/django \
    && mkdir -p /etc/service/bokeh  \
    && touch /etc/service/django/run /etc/service/bokeh/run /etc/postgresql-backup-pre \
    && chmod a+x /etc/service/django/run /etc/service/bokeh/run /etc/postgresql-backup-pre \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY ./deploy/db/autopostgresqlbackup.conf /etc/default/autopostgresqlbackup
COPY ./deploy/db/postgresql-backup-pre /etc/
COPY ${RUN_SCRIPT} /etc/service/django/run
COPY ./deploy/docker/bokeh.sh /etc/service/bokeh/run

COPY deploy/mail/ssmtp.conf /etc/ssmtp/ssmtp.conf
# copy cron script to be run daily
COPY deploy/cron/daily_catalog_tasks /etc/cron.daily/
COPY deploy/cron/monthly_catalog_tasks /etc/cron.monthly/

WORKDIR /code
COPY citation /code/citation
COPY requirements.txt /code/
# Set execute bit on the cron script and install pip dependencies
RUN chmod +x /etc/cron.daily/daily_catalog_tasks && chmod +x /etc/cron.monthly/monthly_catalog_tasks \
    && pip3 install -r /code/requirements.txt

COPY . /code
CMD ["/sbin/my_init"]
