FROM comses/base

RUN apk add -q --no-cache musl-dev gcc python3-dev postgresql-dev libxml2-dev libxslt-dev postgresql build-base \
        pcre-dev linux-headers \
# utility dependencies
        curl git bash mutt ssmtp mailx

ENV PYTHONUNBUFFERED 1
COPY requirements.txt /tmp/
RUN pip3 install -q -r /tmp/requirements.txt

COPY deploy/mail/ssmtp.conf /etc/ssmtp/ssmtp.conf

WORKDIR /code
CMD ["/code/deploy/docker/dev.sh"]
