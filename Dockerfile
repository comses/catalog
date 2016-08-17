FROM comses/base

RUN apk add -q --no-cache --virtual=build_dependencies musl-dev gcc python3-dev postgresql-dev libxml2-dev libxslt-dev uwsgi curl git bash postgresql

ENV PYTHONUNBUFFERED 1
COPY requirements.txt /tmp/
RUN pip install -q -r /tmp/requirements.txt

ARG cmd="dev.sh"

WORKDIR /code
CMD ["/code/deploy/docker/$cmd"]
