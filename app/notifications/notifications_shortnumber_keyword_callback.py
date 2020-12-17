from flask import Blueprint
from flask import current_app
from flask import json
from flask import request, jsonify

from app import statsd_client
from app.errors import InvalidRequest, register_errors
from app.notifications.process_client_response import validate_callback_data, process_shortnumber_keyword_client_response
from app.dao.services_dao import dao_fetch_service_by_inbound_shortnumber
from app.models import INBOUND_SMS_KEYWORD_TYPE, SMS_TYPE

shortnumber_keyword_callback_blueprint = Blueprint("shortnumber_keyword_callback", __name__, url_prefix="/notifications/sms/shortnumber_keyword")
register_errors(shortnumber_keyword_callback_blueprint)


@shortnumber_keyword_callback_blueprint.route('/sinch', methods=['POST'])
def process_sinch_response():
    client_name = 'Sinch'

    data = json.loads(request.data)
    errors = validate_callback_data(
        data=data,
        fields=['id','from','to','body','received_at'],
        client_name=client_name
    )

    if errors:
        raise InvalidRequest(errors, status_code=400)

    short_number = data.get('to')

    service = fetch_potential_service(short_number, 'sinch')
    if not service:
        return jsonify({
            "status": "ok"
        }), 200
    
    success, errors = process_shortnumber_keyword_client_response(
        service=service,
        short_number=short_number,
        from_number=data.get('from'),
        body=data.get('body'),
        received_at=data.get('received_at'),
        provider_ref=data.get('id'),
        client_name=client_name
    )

    redacted_data = dict(data.items())
    current_app.logger.debug(
        "Keyword shortnumber acknowledge from {} \n{}".format(client_name, redacted_data))
    if errors:
        raise InvalidRequest(errors, status_code=400)
    else:
        return jsonify(result='success', message=success), 200


def fetch_potential_service(short_number, provider_name):
    service = dao_fetch_service_by_inbound_shortnumber(short_number)

    if not service:
        current_app.logger.error('Shortnumber "{}" from {} not associated with a service'.format(
            short_number, provider_name
        ))
        statsd_client.incr('inbound_shortnumber.{}.failed'.format(provider_name))
        return False

    if not has_inbound_shortnumber_permissions(service.permissions):
        current_app.logger.error(
            'Service "{}" does not allow inbound ShortNumber'.format(service.id))
        return False

    return service


def has_inbound_shortnumber_permissions(permissions):
    str_permissions = [p.permission for p in permissions]
    return set([INBOUND_SMS_KEYWORD_TYPE, SMS_TYPE]).issubset(set(str_permissions))