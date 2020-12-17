from flask import current_app
from notifications_utils.statsd_decorators import statsd
from sqlalchemy import desc, and_
from sqlalchemy.orm import aliased

from app import db
from app.dao.dao_utils import transactional
from app.models import InboundSmsKeyword, Service, ServiceDataRetention, SMS_TYPE
from app.utils import midnight_n_days_ago


@transactional
def dao_create_inbound_sms_keyword(inbound_sms_keyword):
    db.session.add(inbound_sms_keyword)


def dao_get_inbound_sms_keyword_for_service(service_id, user_number=None, *, limit_days=None, limit=None):
    q = InboundSmsKeyword.query.filter(
        InboundSmsKeyword.service_id == service_id
    ).order_by(
        InboundSmsKeyword.created_at.desc()
    )
    if limit_days is not None:
        start_date = midnight_n_days_ago(limit_days)
        q = q.filter(InboundSmsKeyword.created_at >= start_date)

    if user_number:
        q = q.filter(InboundSmsKeyword.user_number == user_number)

    if limit:
        q = q.limit(limit)

    return q.all()


def dao_count_inbound_sms_keyword_for_service(service_id, limit_days):
    return InboundSmsKeyword.query.filter(
        InboundSmsKeyword.service_id == service_id,
        InboundSmsKeyword.created_at >= midnight_n_days_ago(limit_days)
    ).count()


def _delete_inbound_sms_keyword(datetime_to_delete_from, query_filter):
    query_limit = 10000

    subquery = db.session.query(
        InboundSmsKeyword.id
    ).filter(
        InboundSmsKeyword.created_at < datetime_to_delete_from,
        *query_filter
    ).limit(
        query_limit
    ).subquery()

    deleted = 0
    # set to nonzero just to enter the loop
    number_deleted = 1
    while number_deleted > 0:
        number_deleted = InboundSmsKeyword.query.filter(InboundSmsKeyword.id.in_(subquery)).delete(synchronize_session='fetch')
        deleted += number_deleted

    return deleted


@statsd(namespace="dao")
@transactional
def delete_inbound_sms_keyword_older_than_retention():
    current_app.logger.info('Deleting inbound sms for services with flexible data retention')

    flexible_data_retention = ServiceDataRetention.query.join(
        ServiceDataRetention.service,
        Service.inbound_number
    ).filter(
        ServiceDataRetention.notification_type == SMS_TYPE
    ).all()

    deleted = 0
    for f in flexible_data_retention:
        n_days_ago = midnight_n_days_ago(f.days_of_retention)

        current_app.logger.info("Deleting inbound sms for service id: {}".format(f.service_id))
        deleted += _delete_inbound_sms(n_days_ago, query_filter=[InboundSmsKeyword.service_id == f.service_id])

    current_app.logger.info('Deleting inbound sms keyword for services without flexible data retention')

    seven_days_ago = midnight_n_days_ago(7)

    deleted += _delete_inbound_sms(seven_days_ago, query_filter=[
        InboundSmsKeyword.service_id.notin_(x.service_id for x in flexible_data_retention),
    ])

    current_app.logger.info('Deleted {} inbound sms keyword'.format(deleted))

    return deleted


def dao_get_inbound_sms_keyword_by_id(service_id, inbound_id):
    return InboundSmsKeyword.query.filter_by(
        id=inbound_id,
        service_id=service_id
    ).one()
