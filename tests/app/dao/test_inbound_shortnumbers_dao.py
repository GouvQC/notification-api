import pytest
from sqlalchemy.exc import IntegrityError

from app.dao.inbound_shortnumbers_dao import (
    dao_get_inbound_shortnumbers,
    dao_get_inbound_shortnumber_for_service,
    dao_get_available_inbound_shortnumbers,
    dao_set_inbound_shortnumber_to_service,
    dao_set_inbound_shortnumber_active_flag,
    dao_allocate_shortnumber_for_service,
    dao_add_inbound_shortnumber)
from app.models import InboundShortNumber

from tests.app.db import create_service, create_inbound_shortnumber


def test_get_inbound_shortnumbers(notify_db, notify_db_session, sample_inbound_shortnumbers):
    res = dao_get_inbound_shortnumbers()

    assert len(res) == len(sample_inbound_shortnumbers)
    assert res == sample_inbound_shortnumbers


def test_get_available_inbound_shortnumbers(notify_db, notify_db_session):
    inbound_shortnumber = create_inbound_shortnumber(shortnumber='1')

    res = dao_get_available_inbound_shortnumbers()

    assert len(res) == 1
    assert res[0] == inbound_shortnumber


def test_set_service_id_on_inbound_shortnumber(notify_db, notify_db_session, sample_inbound_shortnumbers):
    service = create_service(service_name='test service')
    numbers = dao_get_available_inbound_shortnumbers()

    dao_set_inbound_shortnumber_to_service(service.id, numbers[0])

    res = InboundShortNumber.query.filter(InboundShortNumber.service_id == service.id).all()

    assert len(res) == 1
    assert res[0].service_id == service.id


def test_after_setting_service_id_that_inbound_shortnumber_is_unavailable(
        notify_db, notify_db_session, sample_inbound_shortnumbers):
    service = create_service(service_name='test service')
    shortnumbers = dao_get_available_inbound_shortnumbers()

    assert len(shortnumbers) == 1

    dao_set_inbound_shortnumber_to_service(service.id, shortnumbers[0])

    res = dao_get_available_inbound_shortnumbers()

    assert len(res) == 0


def test_setting_a_service_twice_will_raise_an_error(notify_db, notify_db_session):
    create_inbound_shortnumber(shortnumber='1')
    create_inbound_shortnumber(shortnumber='2')
    service = create_service(service_name='test service')
    shortnumbers = dao_get_available_inbound_shortnumbers()

    dao_set_inbound_shortnumber_to_service(service.id, shortnumbers[0])

    with pytest.raises(IntegrityError) as e:
        dao_set_inbound_shortnumber_to_service(service.id, shortnumbers[1])

    assert 'duplicate key value violates unique constraint' in str(e.value)


@pytest.mark.parametrize("active", [True, False])
def test_set_inbound_shortnumber_active_flag(notify_db, notify_db_session, sample_service, active):
    inbound_shortnumber = create_inbound_shortnumber(shortnumber='1')
    dao_set_inbound_shortnumber_to_service(sample_service.id, inbound_shortnumber)

    dao_set_inbound_shortnumber_active_flag(sample_service.id, active=active)

    inbound_number = dao_get_inbound_shortnumber_for_service(sample_service.id)

    assert inbound_shortnumber.active is active


def test_dao_allocate_shortnumber_for_service(notify_db_session):
    shortnumber = '078945612'
    inbound_shortnumber = create_inbound_shortnumber(shortnumber=shortnumber)
    service = create_service()

    updated_inbound_shortnumber = dao_allocate_shortnumber_for_service(service_id=service.id, inbound_shortnumber_id=inbound_shortnumber.id)
    assert service.get_inbound_shortnumber() == shortnumber
    assert updated_inbound_shortnumber.service_id == service.id


def test_dao_allocate_shortnumber_for_service_raises_if_inbound_shortnumber_already_taken(notify_db_session, sample_service):
    shortnumber = '078945612'
    inbound_shortnumber = create_inbound_shortnumber(shortnumber=shortnumber, service_id=sample_service.id)
    service = create_service(service_name="Service needs an inbound shortnumber")
    with pytest.raises(Exception) as exc:
        dao_allocate_shortnumber_for_service(service_id=service.id, inbound_shortnumber_id=inbound_shortnumber.id)
    assert 'is not available' in str(exc.value)


def test_dao_allocate_shortnumber_for_service_raises_if_invalid_inbound_shortnumber(notify_db_session, fake_uuid):
    service = create_service(service_name="Service needs an inbound shortnumber")
    with pytest.raises(Exception) as exc:
        dao_allocate_shortnumber_for_service(service_id=service.id, inbound_shortnumber_id=fake_uuid)
    assert 'is not available' in str(exc.value)


def test_dao_add_inbound_shortnumber(notify_db_session):
    inbound_shortnumber = '12345678901'
    dao_add_inbound_shortnumber(inbound_shortnumber)

    res = dao_get_available_inbound_shortnumbers()

    assert len(res) == 1
    assert res[0].short_number == inbound_shortnumber
