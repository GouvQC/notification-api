FROM python:3.6-alpine

ENV PYTHONDONTWRITEBYTECODE 1

RUN apk add --no-cache bash build-base git gcc musl-dev postgresql-dev g++ make libffi-dev libmagic openssl && rm -rf /var/cache/apk/*

# update pip
RUN python -m pip install wheel
RUN python -m pip install --upgrade pip

RUN set -ex && mkdir /app

WORKDIR /app

COPY ./requirements.txt /app
COPY ./requirements_for_test.txt /app

RUN set -ex && python -m pip install --no-cache-dir -r requirements.txt
# RUN set -ex && pip3 install --no-cache-dir --force-reinstall -r requirements_for_test.txt
RUN set -ex && python -m pip install celery==4.2.0rc4

COPY . /app

# Ajout du certificat RQ
RUN cat /app/Certificats/rq_ca.crt >> /usr/local/lib/python3.6/site-packages/certifi/cacert.pem

RUN make generate-version-file
