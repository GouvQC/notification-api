FROM python:3.6-alpine

ENV PYTHONDONTWRITEBYTECODE 1

RUN apk add --no-cache bash build-base git gcc musl-dev postgresql-dev g++ make libffi-dev libmagic openssl && rm -rf /var/cache/apk/*

# update pip
RUN python -m pip install wheel

RUN set -ex && mkdir /app

WORKDIR /app

COPY ./Certificats/cluster-ca.cer /app
#Transformation du certificat .cer en .crt avec OpenSSL
RUN openssl x509 -inform PEM -in /app/cluster-ca.cer -out /usr/share/ca-certificates/cluster-ca.crt
#Ajout de l'information du certificat dans le fichier de configuration des certificats de Ubuntu
RUN echo "cluster-ca.crt" >> /etc/ca-certificates.conf
#Exécution de l'outil de mise à jour des certificats (Basé sur le fichier /etc/ca-certificates.conf, modifié plus tôt)
RUN update-ca-certificates

COPY ./requirements.txt /app
COPY ./requirements_for_test.txt /app

RUN set -ex && pip3 install -r requirements.txt
RUN set -ex && pip3 install -r requirements_for_test.txt
RUN set -ex && pip3 install celery==4.2.0rc4

COPY . /app

RUN make generate-version-file
