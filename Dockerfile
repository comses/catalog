FROM comses/base

RUN apk add --no-cache --virtual=build_dependencies musl-dev gcc python3-dev postgresql-dev libxml2-dev libxslt-dev uwsgi curl git bash postgresql

ENV PYTHONUNBUFFERED 1

COPY requirements.txt /tmp/
RUN pip install -r /tmp/requirements.txt
ARG settingsfile=local.py.example
WORKDIR /code
COPY catalog/settings/$settingsfile /code/catalog/settings/local.py
CMD ["/code/deploy/docker/entrypoint.sh"]
