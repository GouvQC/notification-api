FROM python:3.6-alpine

ENV PYTHONDONTWRITEBYTECODE 1

RUN apk add --no-cache bash build-base git gcc musl-dev postgresql-dev g++ make libffi-dev libmagic openssl && rm -rf /var/cache/apk/*

# update pip
RUN python -m pip install wheel

RUN set -ex && mkdir /app

WORKDIR /app

# Ajout du certificat RQ
#COPY ./Certificats/rq_ca.crt /usr/local/share/ca-certificates/extra
COPY ./Certificats/rq_ca.crt /usr/share/ca-certificates/mozilla
RUN update-ca-certificates

COPY ./requirements.txt /app
COPY ./requirements_for_test.txt /app

RUN set -ex && pip3 install -r requirements.txt
RUN set -ex && pip3 install -r requirements_for_test.txt
RUN set -ex && pip3 install celery==4.2.0rc4

# Ajout du certificat RQ
#COPY ./Certificats/rq_ca.crt /usr/local/share/ca-certificates/extra
COPY ./Certificats/rq_ca.crt /app
CMD cat /app/rq_ca.crt >> /usr/local/lib/python3.6/site-packages/certifi/cacert.pem
#RUN update-ca-certificates

COPY . /app

RUN make generate-version-file
