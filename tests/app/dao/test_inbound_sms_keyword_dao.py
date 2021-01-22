from datetime import datetime
from itertools import product
from freezegun import freeze_time

from app.dao.inbound_sms_keyword_dao import (
    dao_get_inbound_sms_keyword_for_service,
    dao_count_inbound_sms_keyword_for_service,
    delete_inbound_sms_keyword_older_than_retention,
    dao_get_inbound_sms_keyword_by_id
)
from tests.app.db import create_inbound_sms_keyword, create_service, create_service_data_retention


def test_get_all_inbound_sms_keyword(sample_service):
    inbound = create_inbound_sms_keyword(sample_service)

    res = dao_get_inbound_sms_keyword_for_service(sample_service.id)
    assert len(res) == 1
    assert res[0] == inbound


def test_get_all_inbound_sms_keyword_when_none_exist(sample_service):
    res = dao_get_inbound_sms_keyword_for_service(sample_service.id)
    assert len(res) == 0


def test_get_all_inbound_sms_keywords_limits_and_orders(sample_service):
    with freeze_time('2017-01-01'):
        create_inbound_sms_keyword(sample_service)
    with freeze_time('2017-01-03'):
        three = create_inbound_sms_keyword(sample_service)
    with freeze_time('2017-01-02'):
        two = create_inbound_sms_keyword(sample_service)

        res = dao_get_inbound_sms_keyword_for_service(sample_service.id, limit=2)

    assert len(res) == 2
    assert res[0] == three
    assert res[0].created_at == datetime(2017, 1, 3)
    assert res[1] == two
    assert res[1].created_at == datetime(2017, 1, 2)


def test_get_all_inbound_sms_keyword_filters_on_service(notify_db_session):
    service_one = create_service(service_name='one')
    service_two = create_service(service_name='two')

    sms_one = create_inbound_sms_keyword(service_one)
    create_inbound_sms_keyword(service_two)

    res = dao_get_inbound_sms_keyword_for_service(service_one.id)
    assert len(res) == 1
    assert res[0] == sms_one


# This test assumes the local timezone is EST
def test_get_all_inbound_sms_keyword_filters_on_time(sample_service, notify_db_session):
    create_inbound_sms_keyword(sample_service, created_at=datetime(2017, 8, 7, 3, 59))  # sunday evening
    sms_two = create_inbound_sms_keyword(sample_service, created_at=datetime(2017, 8, 7, 4, 0))  # monday (7th) morning

    with freeze_time('2017-08-14 12:00'):
        res = dao_get_inbound_sms_keyword_for_service(sample_service.id, limit_days=7)

    assert len(res) == 1
    assert res[0] == sms_two


def test_count_inbound_sms_keyword_for_service(notify_db_session):
    service_one = create_service(service_name='one')
    service_two = create_service(service_name='two')

    create_inbound_sms_keyword(service_one)
    create_inbound_sms_keyword(service_one)
    create_inbound_sms_keyword(service_two)

    assert dao_count_inbound_sms_keyword_for_service(service_one.id, limit_days=1) == 2


# This test assumes the local timezone is EST
def test_count_inbound_sms_keyword_for_service_filters_messages_older_than_n_days(sample_service):
    # test between evening sunday 2nd of june and morning of monday 3rd
    create_inbound_sms_keyword(sample_service, created_at=datetime(2019, 6, 3, 3, 59))
    create_inbound_sms_keyword(sample_service, created_at=datetime(2019, 6, 3, 3, 59))
    create_inbound_sms_keyword(sample_service, created_at=datetime(2019, 6, 3, 4, 1))

    with freeze_time('Monday 10th June 2019 12:00'):
        assert dao_count_inbound_sms_keyword_for_service(sample_service.id, limit_days=7) == 1


@freeze_time("2017-06-08 12:00:00")
# This test assumes the local timezone is EST
def test_should_delete_inbound_sms_keyword_according_to_data_retention(notify_db_session):
    no_retention_service = create_service(service_name='no retention')
    short_retention_service = create_service(service_name='three days')
    long_retention_service = create_service(service_name='thirty days')

    services = [short_retention_service, no_retention_service, long_retention_service]

    create_service_data_retention(long_retention_service, notification_type='sms', days_of_retention=30)
    create_service_data_retention(short_retention_service, notification_type='sms', days_of_retention=3)
    # email retention doesn't affect anything
    create_service_data_retention(short_retention_service, notification_type='email', days_of_retention=4)

    dates = [
        datetime(2017, 6, 5, 3, 59),  # older than three days
        datetime(2017, 6, 1, 3, 59),  # older than seven days
        datetime(2017, 5, 1, 0, 0),  # older than thirty days
    ]

    for date, service in product(dates, services):
        create_inbound_sms_keyword(service, created_at=date)

    deleted_count = delete_inbound_sms_keyword_older_than_retention()

    assert deleted_count == 6
    assert {
        x.created_at for x in dao_get_inbound_sms_keyword_for_service(short_retention_service.id)
    } == set(dates[:1])
    assert {
        x.created_at for x in dao_get_inbound_sms_keyword_for_service(no_retention_service.id)
    } == set(dates[:1])
    assert {
        x.created_at for x in dao_get_inbound_sms_keyword_for_service(long_retention_service.id)
    } == set(dates[:1])


def test_get_inbound_sms_keyword_by_id_returns(sample_service):
    inbound_sms_keyword = create_inbound_sms_keyword(service=sample_service)
    inbound_from_db = dao_get_inbound_sms_keyword_by_id(inbound_sms_keyword.service.id, inbound_sms_keyword.id)

    assert inbound_sms_keyword == inbound_from_db
