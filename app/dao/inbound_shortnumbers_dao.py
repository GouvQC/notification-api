import uuid
from app import db
from app.dao.dao_utils import transactional
from app.models import InboundShortNumber


def dao_get_inbound_shortnumbers():
    return InboundShortNumber.query.order_by(InboundShortNumber.updated_at).all()


def dao_get_available_inbound_shortnumbers():
    return InboundShortNumber.query.filter(InboundShortNumber.active, InboundShortNumber.service_id.is_(None)).all()


def dao_get_inbound_shortnumber_for_service(service_id):
    return InboundShortNumber.query.filter(InboundShortNumber.service_id == service_id).first()


def dao_get_inbound_shortnumber(inbound_shortnumber_id):
    return InboundShortNumber.query.filter(InboundShortNumber.id == inbound_shortnumber_id).first()


@transactional
def dao_set_inbound_shortnumber_to_service(service_id, inbound_shortnumber):
    inbound_shortnumber.service_id = service_id
    db.session.add(inbound_shortnumber)


@transactional
def dao_set_inbound_shortnumber_active_flag(service_id, active):
    inbound_shortnumber = InboundShortNumber.query.filter(InboundShortNumber.service_id == service_id).first()
    inbound_shortnumber.active = active

    db.session.add(inbound_shortnumber)


@transactional
def dao_allocate_shortnumber_for_service(service_id, inbound_shortnumber_id):
    updated = InboundShortNumber.query.filter_by(
        id=inbound_shortnumber_id,
        active=True,
        service_id=None
    ).update(
        {"service_id": service_id}
    )
    if not updated:
        raise Exception("Inbound shortnumber: {} is not available".format(inbound_shortnumber_id))
    return InboundShortNumber.query.get(inbound_shortnumber_id)


def dao_add_inbound_shortnumber(inbound_shortnumber):
    sql = "insert into inbound_shortnumbers values('{}', '{}', 'sinch', null, True, now(), null);"
    db.session.execute(sql.format(uuid.uuid4(), inbound_shortnumber))
    db.session.commit()
