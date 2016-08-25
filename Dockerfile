FROM comses/base

RUN apk update && apk upgrade
RUN apk add -q --no-cache musl-dev gcc python3-dev postgresql-dev libxml2-dev libxslt-dev postgresql build-base pcre-dev linux-headers

ENV PYTHONUNBUFFERED 1
COPY requirements.txt /tmp/
RUN pip3 install -q -r /tmp/requirements.txt

# utility dependencies
RUN apk add -q curl git bash mutt ssmtp mailx

COPY deploy/mail/ssmtp.conf /etc/ssmtp/ssmtp.conf

ARG cmd="dev.sh"

WORKDIR /code
CMD ["/code/deploy/docker/$cmd"]
