FROM comses/base:0.9.22

RUN apt-get update && apt-get install -q -y libxml2-dev python3-dev python3-pip curl git ssmtp wget cron \
    && echo "deb http://apt.postgresql.org/pub/repos/apt/ xenial-pgdg main" | tee /etc/apt/sources.list.d/postgresql.list \
    && wget -q -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - \
    && apt-get update && apt-get install -q -y postgresql-client-9.6 libpq-dev

ENV PYTHONUNBUFFERED 1
COPY citation /code/citation
COPY requirements.txt /tmp/
RUN pip3 install -q -r /tmp/requirements.txt

COPY deploy/mail/ssmtp.conf /etc/ssmtp/ssmtp.conf

# Add crontask file in the cron directory
ADD crontask /etc/cron.d/cron_caching

# Give execution rights on the cron job
RUN chmod +x /etc/cron.d/cron_caching

WORKDIR /code
CMD ["/code/deploy/docker/dev.sh"]
