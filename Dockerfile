FROM comses/base

RUN apk add -q --no-cache musl-dev gcc python3-dev libxml2-dev libxslt-dev build-base pcre-dev linux-headers \
# utility dependencies
        curl git bash mutt ssmtp mailx

RUN echo @edge http://nl.alpinelinux.org/alpine/edge/main >> /etc/apk/repositories \
        && apk add postgresql-client@edge postgresql@edge postgresql-dev@edge --update-cache --no-cache -q

ENV PYTHONUNBUFFERED 1
COPY requirements.txt /tmp/
RUN pip3 install -q -r /tmp/requirements.txt

COPY deploy/mail/ssmtp.conf /etc/ssmtp/ssmtp.conf

WORKDIR /code
CMD ["/code/deploy/docker/dev.sh"]
