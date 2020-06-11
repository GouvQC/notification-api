FROM python:3.6-alpine

ENV PYTHONDONTWRITEBYTECODE 1

RUN apk add --no-cache bash build-base git gcc musl-dev postgresql-dev g++ make libffi-dev libmagic && rm -rf /var/cache/apk/*

# update pip
RUN python -m pip install wheel

RUN set -ex && mkdir /app

WORKDIR /app

COPY ./requirements.txt /app
COPY ./requirements_for_test.txt /app

RUN set -ex && pip3 install -r requirements.txt
RUN set -ex && pip3 install -r requirements_for_test.txt
RUN set -ex && pip3 install celery==4.2.0rc4

COPY . /app

RUN make generate-version-file

# Répertoire de travail
WORKDIR /app
RUN chmod g+w .

COPY [".devcontainer/start.sh", "start.sh"]
RUN chmod +x start.sh
RUN chmod g+w /etc/passwd


CMD ["./start.sh"]
