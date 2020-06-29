FROM python:3.6-alpine

ENV PYTHONDONTWRITEBYTECODE 1

RUN apk add --no-cache openssl bash build-base git gcc musl-dev postgresql-dev g++ make libffi-dev libmagic && rm -rf /var/cache/apk/*

# update pip
RUN python -m pip install wheel

RUN set -ex && mkdir /src && mkdir /src/Certificats
COPY Certificats/RQ_CA.cer /src/Certificats
RUN openssl x509 -inform PEM -in /src/Certificats/RQ_CA.cer -out /src/Certificats/RQ_CA.crt
RUN cp /src/Certificats/RQ_CA.crt /usr/share/ca-certificates/RQ_CA.crt
RUN echo "RQ_CA.crt" >> /etc/ca-certificates.conf && update-ca-certificates

RUN set -ex && mkdir /app

WORKDIR /app

COPY ./requirements.txt /app
COPY ./requirements_for_test.txt /app

RUN set -ex && pip3 install -r requirements.txt
RUN set -ex && pip3 install -r requirements_for_test.txt
RUN set -ex && pip3 install celery==4.2.0rc4

COPY . /app

RUN make generate-version-file
