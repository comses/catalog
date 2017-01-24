FROM comses/base

RUN apt-get update && apt-get install -y libxml2-dev python3-dev python3-pip curl git ssmtp wget \
    && echo "deb http://apt.postgresql.org/pub/repos/apt/ xenial-pgdg main" | tee /etc/apt/sources.list.d/postgresql.list \
    && wget -q -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - \
    && apt-get update && apt-get install -y postgresql-client-9.6 libpq-dev

ENV PYTHONUNBUFFERED 1
COPY requirements.txt /tmp/
RUN pip3 install -q -r /tmp/requirements.txt

COPY deploy/mail/ssmtp.conf /etc/ssmtp/ssmtp.conf

WORKDIR /code
CMD ["/code/deploy/docker/dev.sh"]
