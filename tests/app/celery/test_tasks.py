import uuid
from datetime import datetime

import pytest
from freezegun import freeze_time
from mock import ANY
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import NoResultFound

from app import (aws_ses_client, encryption, DATETIME_FORMAT, statsd_client, db)
from app.celery import provider_tasks
from app.celery import tasks
from app.celery.research_mode_tasks import send_email_response
from app.celery.tasks import s3
from app.celery.tasks import (
    send_sms,
    process_job,
    provider_to_use,
    send_email
)
from app.clients.email.aws_ses import AwsSesClientException
from app.dao import notifications_dao, jobs_dao, provider_details_dao
from app.dao.provider_statistics_dao import get_provider_statistics
from app.models import Notification
from tests.app import load_example_csv
from tests.app.conftest import (
    sample_service,
    sample_user,
    sample_template,
    sample_job,
    sample_email_template,
    sample_notification
)


class AnyStringWith(str):
    def __eq__(self, other):
        return self in other


mmg_error = {'Error': '40', 'Description': 'error'}


def _notification_json(template, to, personalisation=None, job_id=None, row_number=None):
    notification = {
        "template": str(template.id),
        "template_version": template.version,
        "to": to,
    }
    if personalisation:
        notification.update({"personalisation": personalisation})
    if job_id:
        notification.update({"job": str(job_id)})
    if row_number:
        notification['row_number'] = row_number
    return notification


# TODO moved to test_provider_tasks once send-email migrated
def test_should_return_highest_priority_active_provider(notify_db, notify_db_session):
    providers = provider_details_dao.get_provider_details_by_notification_type('sms')
    first = providers[0]
    second = providers[1]

    assert provider_to_use('sms', '1234').name == first.identifier

    first.priority = 20
    second.priority = 10

    provider_details_dao.dao_update_provider_details(first)
    provider_details_dao.dao_update_provider_details(second)

    assert provider_to_use('sms', '1234').name == second.identifier

    first.priority = 10
    first.active = False
    second.priority = 20

    provider_details_dao.dao_update_provider_details(first)
    provider_details_dao.dao_update_provider_details(second)

    assert provider_to_use('sms', '1234').name == second.identifier

    first.active = True
    provider_details_dao.dao_update_provider_details(first)

    assert provider_to_use('sms', '1234').name == first.identifier


@freeze_time("2016-01-01 11:09:00.061258")
def test_should_process_sms_job(sample_job, mocker, mock_celery_remove_job):
    mocker.patch('app.statsd_client.incr')
    mocker.patch('app.statsd_client.timing')
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('sms'))
    mocker.patch('app.celery.tasks.send_sms.apply_async')
    mocker.patch('app.encryption.encrypt', return_value="something_encrypted")
    mocker.patch('app.celery.tasks.create_uuid', return_value="uuid")

    process_job(sample_job.id)
    s3.get_job_from_s3.assert_called_once_with(
        str(sample_job.service.id),
        str(sample_job.id)
    )
    assert encryption.encrypt.call_args[0][0]['to'] == '+441234123123'
    assert encryption.encrypt.call_args[0][0]['template'] == str(sample_job.template.id)
    assert encryption.encrypt.call_args[0][0]['template_version'] == sample_job.template.version
    assert encryption.encrypt.call_args[0][0]['personalisation'] == {}
    assert encryption.encrypt.call_args[0][0]['row_number'] == 0
    tasks.send_sms.apply_async.assert_called_once_with(
        (str(sample_job.service_id),
         "uuid",
         "something_encrypted",
         "2016-01-01T11:09:00.061258"),
        queue="bulk-sms"
    )
    job = jobs_dao.dao_get_job_by_id(sample_job.id)
    assert job.status == 'finished'
    statsd_client.incr.assert_called_once_with("notifications.tasks.process-job")
    statsd_client.timing.assert_called_once_with("notifications.tasks.process-job.task-time", ANY)


@freeze_time("2016-01-01 11:09:00.061258")
def test_should_not_process_sms_job_if_would_exceed_send_limits(notify_db,
                                                                notify_db_session,
                                                                mocker,
                                                                mock_celery_remove_job):
    service = sample_service(notify_db, notify_db_session, limit=9)
    job = sample_job(notify_db, notify_db_session, service=service, notification_count=10)

    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_sms'))
    mocker.patch('app.celery.tasks.send_sms.apply_async')
    mocker.patch('app.encryption.encrypt', return_value="something_encrypted")
    mocker.patch('app.celery.tasks.create_uuid', return_value="uuid")

    process_job(job.id)

    s3.get_job_from_s3.assert_not_called()
    job = jobs_dao.dao_get_job_by_id(job.id)
    assert job.status == 'sending limits exceeded'
    tasks.send_sms.apply_async.assert_not_called()
    mock_celery_remove_job.assert_not_called()


def test_should_not_process_sms_job_if_would_exceed_send_limits_inc_today(notify_db,
                                                                          notify_db_session,
                                                                          mocker,
                                                                          mock_celery_remove_job):
    service = sample_service(notify_db, notify_db_session, limit=1)
    job = sample_job(notify_db, notify_db_session, service=service)

    sample_notification(notify_db, notify_db_session, service=service, job=job)

    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('sms'))
    mocker.patch('app.celery.tasks.send_sms.apply_async')
    mocker.patch('app.encryption.encrypt', return_value="something_encrypted")
    mocker.patch('app.celery.tasks.create_uuid', return_value="uuid")

    process_job(job.id)

    job = jobs_dao.dao_get_job_by_id(job.id)
    assert job.status == 'sending limits exceeded'
    s3.get_job_from_s3.assert_not_called()
    tasks.send_sms.apply_async.assert_not_called()
    mock_celery_remove_job.assert_not_called()


def test_should_not_process_email_job_if_would_exceed_send_limits_inc_today(notify_db, notify_db_session, mocker):
    service = sample_service(notify_db, notify_db_session, limit=1)
    template = sample_email_template(notify_db, notify_db_session, service=service)
    job = sample_job(notify_db, notify_db_session, service=service, template=template)

    sample_notification(notify_db, notify_db_session, service=service, job=job)

    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('email'))
    mocker.patch('app.celery.tasks.send_email.apply_async')
    mocker.patch('app.encryption.encrypt', return_value="something_encrypted")
    mocker.patch('app.celery.tasks.create_uuid', return_value="uuid")

    process_job(job.id)

    job = jobs_dao.dao_get_job_by_id(job.id)
    assert job.status == 'sending limits exceeded'
    s3.get_job_from_s3.assert_not_called()
    tasks.send_email.apply_async.assert_not_called()


@freeze_time("2016-01-01 11:09:00.061258")
def test_should_not_process_email_job_if_would_exceed_send_limits(notify_db, notify_db_session, mocker):
    service = sample_service(notify_db, notify_db_session, limit=0)
    template = sample_email_template(notify_db, notify_db_session, service=service)
    job = sample_job(notify_db, notify_db_session, service=service, template=template)

    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('email'))
    mocker.patch('app.celery.tasks.send_email.apply_async')
    mocker.patch('app.encryption.encrypt', return_value="something_encrypted")
    mocker.patch('app.celery.tasks.create_uuid', return_value="uuid")

    process_job(job.id)

    s3.get_job_from_s3.assert_not_called
    job = jobs_dao.dao_get_job_by_id(job.id)
    assert job.status == 'sending limits exceeded'
    tasks.send_email.apply_async.assert_not_called


@freeze_time("2016-01-01 11:09:00.061258")
def test_should_process_email_job_if_exactly_on_send_limits(notify_db,
                                                            notify_db_session,
                                                            mocker,
                                                            mock_celery_remove_job):
    service = sample_service(notify_db, notify_db_session, limit=10)
    template = sample_email_template(notify_db, notify_db_session, service=service)
    job = sample_job(notify_db, notify_db_session, service=service, template=template, notification_count=10)

    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_email'))
    mocker.patch('app.celery.tasks.send_email.apply_async')
    mocker.patch('app.encryption.encrypt', return_value="something_encrypted")
    mocker.patch('app.celery.tasks.create_uuid', return_value="uuid")

    process_job(job.id)

    s3.get_job_from_s3.assert_called_once_with(
        str(job.service.id),
        str(job.id)
    )
    job = jobs_dao.dao_get_job_by_id(job.id)
    assert job.status == 'finished'
    tasks.send_email.apply_async.assert_called_with(
        (
            str(job.service_id),
            "uuid",
            "something_encrypted",
            "2016-01-01T11:09:00.061258"
        ),
        {'reply_to_addresses': None},
        queue="bulk-email"
    )
    mock_celery_remove_job.assert_called_once_with((str(job.id),), queue="remove-job")


def test_should_not_create_send_task_for_empty_file(sample_job, mocker, mock_celery_remove_job):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('empty'))
    mocker.patch('app.celery.tasks.send_sms.apply_async')

    process_job(sample_job.id)

    s3.get_job_from_s3.assert_called_once_with(
        str(sample_job.service.id),
        str(sample_job.id)
    )
    job = jobs_dao.dao_get_job_by_id(sample_job.id)
    assert job.status == 'finished'
    tasks.send_sms.apply_async.assert_not_called


@freeze_time("2016-01-01 11:09:00.061258")
def test_should_process_email_job(sample_email_job, mocker, mock_celery_remove_job):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('email'))
    mocker.patch('app.celery.tasks.send_email.apply_async')
    mocker.patch('app.encryption.encrypt', return_value="something_encrypted")
    mocker.patch('app.celery.tasks.create_uuid', return_value="uuid")

    process_job(sample_email_job.id)

    s3.get_job_from_s3.assert_called_once_with(
        str(sample_email_job.service.id),
        str(sample_email_job.id)
    )
    assert encryption.encrypt.call_args[0][0]['to'] == 'test@test.com'
    assert encryption.encrypt.call_args[0][0]['template'] == str(sample_email_job.template.id)
    assert encryption.encrypt.call_args[0][0]['template_version'] == sample_email_job.template.version
    assert encryption.encrypt.call_args[0][0]['personalisation'] == {}
    tasks.send_email.apply_async.assert_called_once_with(
        (
            str(sample_email_job.service_id),
            "uuid",
            "something_encrypted",
            "2016-01-01T11:09:00.061258"
        ),
        {'reply_to_addresses': None},
        queue="bulk-email"
    )
    job = jobs_dao.dao_get_job_by_id(sample_email_job.id)
    assert job.status == 'finished'
    mock_celery_remove_job.assert_called_once_with((str(job.id),), queue="remove-job")


def test_should_process_all_sms_job(sample_job,
                                    sample_job_with_placeholdered_template,
                                    mocker,
                                    mock_celery_remove_job):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('multiple_sms'))
    mocker.patch('app.celery.tasks.send_sms.apply_async')
    mocker.patch('app.encryption.encrypt', return_value="something_encrypted")
    mocker.patch('app.celery.tasks.create_uuid', return_value="uuid")

    process_job(sample_job_with_placeholdered_template.id)

    s3.get_job_from_s3.assert_called_once_with(
        str(sample_job_with_placeholdered_template.service.id),
        str(sample_job_with_placeholdered_template.id)
    )
    assert encryption.encrypt.call_args[0][0]['to'] == '+441234123120'
    assert encryption.encrypt.call_args[0][0]['template'] == str(sample_job_with_placeholdered_template.template.id)
    assert encryption.encrypt.call_args[0][0][
               'template_version'] == sample_job_with_placeholdered_template.template.version  # noqa
    assert encryption.encrypt.call_args[0][0]['personalisation'] == {'name': 'chris'}
    tasks.send_sms.apply_async.call_count == 10
    job = jobs_dao.dao_get_job_by_id(sample_job_with_placeholdered_template.id)
    assert job.status == 'finished'


def test_should_send_template_to_correct_sms_task_and_persist(sample_template_with_placeholders, mocker):
    notification = _notification_json(sample_template_with_placeholders,
                                      to="+447234123123", personalisation={"name": "Jo"})
    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.statsd_client.incr')
    mocker.patch('app.statsd_client.timing_with_dates')
    mocker.patch('app.statsd_client.timing')
    mocker.patch('app.celery.provider_tasks.send_sms_to_provider.apply_async')

    notification_id = uuid.uuid4()

    freezer = freeze_time("2016-01-01 11:09:00.00000")
    freezer.start()
    now = datetime.utcnow()
    freezer.stop()

    freezer = freeze_time("2016-01-01 11:10:00.00000")
    freezer.start()

    send_sms(
        sample_template_with_placeholders.service_id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )
    freezer.stop()

    statsd_client.timing.assert_called_once_with("notifications.tasks.send-sms.task-time", ANY)

    provider_tasks.send_sms_to_provider.apply_async.assert_called_once_with(
        (sample_template_with_placeholders.service_id,
         notification_id,
         "encrypted-in-reality"),
        queue="sms"
    )

    statsd_client.incr.assert_called_once_with("notifications.tasks.send-sms")
    persisted_notification = Notification.query.filter_by(id=notification_id).one()
    assert persisted_notification.id == notification_id
    assert persisted_notification.to == '+447234123123'
    assert persisted_notification.template_id == sample_template_with_placeholders.id
    assert persisted_notification.template_version == sample_template_with_placeholders.version
    assert persisted_notification.status == 'created'
    assert persisted_notification.created_at == now
    assert not persisted_notification.sent_at
    assert not persisted_notification.sent_by
    assert not persisted_notification.job_id


def test_should_send_sms_if_restricted_service_and_valid_number(notify_db, notify_db_session, mocker):
    user = sample_user(notify_db, notify_db_session, mobile_numnber="07700 900890")
    service = sample_service(notify_db, notify_db_session, user=user, restricted=True)
    template = sample_template(notify_db, notify_db_session, service=service)

    notification = _notification_json(template, "+447700900890")  # The user’s own number, but in a different format

    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.celery.provider_tasks.send_sms_to_provider.apply_async')

    notification_id = uuid.uuid4()
    now = datetime.utcnow()
    send_sms(
        service.id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )

    provider_tasks.send_sms_to_provider.apply_async.assert_called_once_with(
        (service.id,
         notification_id,
         "encrypted-in-reality"),
        queue="sms"
    )

    persisted_notification = Notification.query.filter_by(id=notification_id).one()
    assert persisted_notification.id == notification_id
    assert persisted_notification.to == '+447700900890'
    assert persisted_notification.template_id == template.id
    assert persisted_notification.template_version == template.version
    assert persisted_notification.status == 'created'
    assert persisted_notification.created_at == now
    assert not persisted_notification.sent_at
    assert not persisted_notification.sent_by
    assert not persisted_notification.job_id


def test_should_not_send_sms_if_restricted_service_and_invalid_number(notify_db, notify_db_session, mocker):
    user = sample_user(notify_db, notify_db_session, mobile_numnber="07700 900205")
    service = sample_service(notify_db, notify_db_session, user=user, restricted=True)
    template = sample_template(notify_db, notify_db_session, service=service)

    notification = _notification_json(template, "07700 900849")
    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.celery.provider_tasks.send_sms_to_provider.apply_async')

    notification_id = uuid.uuid4()
    now = datetime.utcnow()
    send_sms(
        service.id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )
    provider_tasks.send_sms_to_provider.apply_async.assert_not_called()
    with pytest.raises(NoResultFound):
        Notification.query.filter_by(id=notification_id).one()


def test_should_send_email_if_restricted_service_and_valid_email(notify_db, notify_db_session, mocker):
    user = sample_user(notify_db, notify_db_session, email="test@restricted.com")
    service = sample_service(notify_db, notify_db_session, user=user, restricted=True)
    template = sample_template(
        notify_db,
        notify_db_session,
        service=service,
        template_type='email')

    notification = _notification_json(template, "test@restricted.com")
    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.aws_ses_client.send_email', return_value="1234")

    notification_id = uuid.uuid4()
    now = datetime.utcnow()
    send_email(
        service.id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )

    aws_ses_client.send_email.assert_called_once_with(
        '"Sample service" <sample.service@test.notify.com>',
        "test@restricted.com",
        template.subject,
        body=template.content,
        html_body=AnyStringWith(template.content),
        reply_to_addresses=None
    )


def test_should_not_send_email_if_restricted_service_and_invalid_email_address(notify_db, notify_db_session, mocker):
    user = sample_user(notify_db, notify_db_session)
    service = sample_service(notify_db, notify_db_session, user=user, restricted=True)
    template = sample_template(
        notify_db, notify_db_session, service=service, template_type='email', subject_line='Hello'
    )

    notification = _notification_json(template, to="test@example.com")
    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.aws_ses_client.send_email')

    notification_id = uuid.uuid4()
    now = datetime.utcnow()
    send_email(
        service.id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )

    aws_ses_client.send_email.assert_not_called()
    with pytest.raises(NoResultFound):
        Notification.query.filter_by(id=notification_id).one()


def test_should_send_template_to_and_persist_with_job_id(sample_job, mocker):
    notification = _notification_json(
        sample_job.template,
        to="+447234123123",
        job_id=sample_job.id,
        row_number=2)
    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.celery.provider_tasks.send_sms_to_provider.apply_async')

    notification_id = uuid.uuid4()
    now = datetime.utcnow()
    send_sms(
        sample_job.service.id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )
    provider_tasks.send_sms_to_provider.apply_async.assert_called_once_with(
        (sample_job.service.id,
         notification_id,
         "encrypted-in-reality"),
        queue="sms"
    )
    persisted_notification = Notification.query.filter_by(id=notification_id).one()
    assert persisted_notification.id == notification_id
    assert persisted_notification.to == '+447234123123'
    assert persisted_notification.job_id == sample_job.id
    assert persisted_notification.template_id == sample_job.template.id
    assert persisted_notification.status == 'created'
    assert not persisted_notification.sent_at
    assert persisted_notification.created_at == now
    assert not persisted_notification.sent_by
    assert persisted_notification.job_row_number == 2


def test_should_use_email_template_and_persist(sample_email_template_with_placeholders, mocker):
    notification = _notification_json(
        sample_email_template_with_placeholders,
        "my_email@my_email.com",
        {"name": "Jo"},
        row_number=1)
    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.statsd_client.incr')
    mocker.patch('app.statsd_client.timing_with_dates')
    mocker.patch('app.statsd_client.timing')
    mocker.patch('app.aws_ses_client.get_name', return_value='ses')
    mocker.patch('app.aws_ses_client.send_email', return_value='ses')

    notification_id = uuid.uuid4()

    freezer = freeze_time("2016-01-01 11:09:00.00000")
    freezer.start()
    now = datetime.utcnow()
    freezer.stop()

    freezer = freeze_time("2016-01-01 11:10:00.00000")
    freezer.start()

    send_email(
        sample_email_template_with_placeholders.service_id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )
    freezer.stop()

    aws_ses_client.send_email.assert_called_once_with(
        '"Sample service" <sample.service@test.notify.com>',
        "my_email@my_email.com",
        notification['personalisation']['name'],
        body="Hello Jo",
        html_body=AnyStringWith("Hello Jo"),
        reply_to_addresses=None
    )

    statsd_client.incr.assert_called_once_with("notifications.tasks.send-email")
    statsd_client.timing_with_dates.assert_called_once_with(
        "notifications.tasks.send-email.queued-for",
        datetime(2016, 1, 1, 11, 10, 0, 00000),
        datetime(2016, 1, 1, 11, 9, 0, 00000)
    )
    statsd_client.timing.assert_called_once_with("notifications.tasks.send-email.task-time", ANY)
    persisted_notification = Notification.query.filter_by(id=notification_id).one()

    assert persisted_notification.id == notification_id
    assert persisted_notification.to == 'my_email@my_email.com'
    assert persisted_notification.template_id == sample_email_template_with_placeholders.id
    assert persisted_notification.template_version == sample_email_template_with_placeholders.version
    assert persisted_notification.created_at == now
    assert persisted_notification.sent_at > now
    assert persisted_notification.status == 'sending'
    assert persisted_notification.sent_by == 'ses'
    assert persisted_notification.job_row_number == 1


def test_send_email_should_use_template_version_from_job_not_latest(sample_email_template, mocker):
    notification = _notification_json(sample_email_template, 'my_email@my_email.com')
    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.aws_ses_client.send_email', return_value="1234")
    mocker.patch('app.aws_ses_client.get_name', return_value='ses')
    version_on_notification = sample_email_template.version
    # Change the template
    from app.dao.templates_dao import dao_update_template, dao_get_template_by_id
    sample_email_template.content = sample_email_template.content + " another version of the template"

    dao_update_template(sample_email_template)
    t = dao_get_template_by_id(sample_email_template.id)
    assert t.version > version_on_notification
    notification_id = uuid.uuid4()
    now = datetime.utcnow()
    send_email(
        sample_email_template.service_id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )
    aws_ses_client.send_email.assert_called_once_with(
        '"Sample service" <sample.service@test.notify.com>',
        "my_email@my_email.com",
        sample_email_template.subject,
        body="This is a template",
        html_body=AnyStringWith("This is a template"),
        reply_to_addresses=None
    )

    persisted_notification = Notification.query.filter_by(id=notification_id).one()
    assert persisted_notification.id == notification_id
    assert persisted_notification.to == 'my_email@my_email.com'
    assert persisted_notification.template_id == sample_email_template.id
    assert persisted_notification.template_version == version_on_notification
    assert persisted_notification.created_at == now
    assert persisted_notification.sent_at > now
    assert persisted_notification.status == 'sending'
    assert persisted_notification.sent_by == 'ses'


def test_should_use_email_template_subject_placeholders(sample_email_template_with_placeholders, mocker):
    notification = _notification_json(sample_email_template_with_placeholders,
                                      "my_email@my_email.com", {"name": "Jo"})
    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.aws_ses_client.send_email', return_value="1234")
    mocker.patch('app.aws_ses_client.get_name', return_value='ses')

    notification_id = uuid.uuid4()
    now = datetime.utcnow()
    send_email(
        sample_email_template_with_placeholders.service_id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )
    aws_ses_client.send_email.assert_called_once_with(
        '"Sample service" <sample.service@test.notify.com>',
        "my_email@my_email.com",
        notification['personalisation']['name'],
        body="Hello Jo",
        html_body=AnyStringWith("Hello Jo"),
        reply_to_addresses=None
    )
    persisted_notification = Notification.query.filter_by(id=notification_id).one()
    assert persisted_notification.id == notification_id
    assert persisted_notification.to == 'my_email@my_email.com'
    assert persisted_notification.template_id == sample_email_template_with_placeholders.id
    assert persisted_notification.created_at == now
    assert persisted_notification.sent_at > now
    assert persisted_notification.status == 'sending'
    assert persisted_notification.sent_by == 'ses'


def test_should_use_email_template_and_persist_ses_reference(sample_email_template_with_placeholders, mocker):
    notification = _notification_json(sample_email_template_with_placeholders, "my_email@my_email.com", {"name": "Jo"})
    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.aws_ses_client.send_email', return_value='reference')

    notification_id = uuid.uuid4()
    now = datetime.utcnow()
    send_email(
        sample_email_template_with_placeholders.service_id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )
    persisted_notification = Notification.query.filter_by(id=notification_id).one()
    assert persisted_notification.reference == 'reference'


def test_should_use_email_template_and_persist_without_personalisation(sample_email_template, mocker):
    mocker.patch('app.encryption.decrypt',
                 return_value=_notification_json(sample_email_template, "my_email@my_email.com"))
    mocker.patch('app.aws_ses_client.send_email', return_value="ref")
    mocker.patch('app.aws_ses_client.get_name', return_value='ses')

    notification_id = uuid.uuid4()
    now = datetime.utcnow()
    send_email(
        sample_email_template.service_id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )
    aws_ses_client.send_email.assert_called_once_with(
        '"Sample service" <sample.service@test.notify.com>',
        "my_email@my_email.com",
        sample_email_template.subject,
        body="This is a template",
        html_body=AnyStringWith("This is a template"),
        reply_to_addresses=None
    )


def test_should_persist_notification_as_failed_if_database_fails(sample_template, mocker):
    notification = _notification_json(sample_template, "+447234123123")

    expected_exception = SQLAlchemyError()

    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.celery.provider_tasks.send_sms_to_provider.apply_async')
    mocker.patch('app.celery.tasks.send_sms.retry', side_effect=Exception())
    mocker.patch('app.celery.tasks.dao_create_notification', side_effect=expected_exception)
    now = datetime.utcnow()

    notification_id = uuid.uuid4()

    with pytest.raises(Exception):
        send_sms(
            sample_template.service_id,
            notification_id,
            "encrypted-in-reality",
            now.strftime(DATETIME_FORMAT)
        )
    provider_tasks.send_sms_to_provider.apply_async.assert_not_called()
    tasks.send_sms.retry.assert_called_with(exc=expected_exception, queue='retry')

    with pytest.raises(NoResultFound) as e:
        Notification.query.filter_by(id=notification_id).one()
    assert 'No row was found for one' in str(e.value)


def test_should_persist_notification_as_failed_if_email_client_fails(sample_email_template, mocker):
    notification = _notification_json(sample_email_template, "my_email@my_email.com")
    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.aws_ses_client.send_email', side_effect=AwsSesClientException())
    mocker.patch('app.aws_ses_client.get_name', return_value="ses")

    now = datetime.utcnow()

    notification_id = uuid.uuid4()

    send_email(
        sample_email_template.service_id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )
    aws_ses_client.send_email.assert_called_once_with(
        '"Sample service" <sample.service@test.notify.com>',
        "my_email@my_email.com",
        sample_email_template.subject,
        body=sample_email_template.content,
        html_body=AnyStringWith(sample_email_template.content),
        reply_to_addresses=None
    )
    persisted_notification = Notification.query.filter_by(id=notification_id).one()
    assert persisted_notification.id == notification_id
    assert persisted_notification.to == 'my_email@my_email.com'
    assert persisted_notification.template_id == sample_email_template.id
    assert persisted_notification.template_version == sample_email_template.version
    assert persisted_notification.status == 'technical-failure'
    assert persisted_notification.created_at == now
    assert persisted_notification.sent_by == 'ses'
    assert persisted_notification.sent_at > now


def test_should_not_send_email_if_db_peristance_failed(sample_email_template, mocker):
    notification = _notification_json(sample_email_template, "my_email@my_email.com")
    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.aws_ses_client.send_email')
    mocker.patch('app.db.session.add', side_effect=SQLAlchemyError())
    now = datetime.utcnow()

    notification_id = uuid.uuid4()

    send_email(
        sample_email_template.service_id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )
    aws_ses_client.send_email.assert_not_called()
    with pytest.raises(NoResultFound) as e:
        Notification.query.filter_by(id=notification_id).one()
    assert 'No row was found for one' in str(e.value)


def test_process_email_job_should_use_reply_to_email_if_present(sample_email_job, mocker, mock_celery_remove_job):
    mocker.patch('app.celery.tasks.s3.get_job_from_s3', return_value=load_example_csv('email'))
    mocker.patch('app.celery.tasks.send_email.apply_async')
    mocker.patch('app.encryption.encrypt', return_value='something_encrypted')
    mocker.patch('app.celery.tasks.create_uuid', return_value='uuid')

    sample_email_job.service.reply_to_email_address = 'somereply@testservice.gov.uk'

    process_job(sample_email_job.id)

    tasks.send_email.apply_async.assert_called_once_with(
        (
            str(sample_email_job.service_id),
            "uuid",
            "something_encrypted",
            ANY
        ),
        {'reply_to_addresses': 'somereply@testservice.gov.uk'},
        queue="bulk-email"
    )


def test_should_call_send_email_response_task_if_research_mode(
        notify_db,
        sample_service,
        sample_email_template,
        mocker):
    notification = _notification_json(
        sample_email_template,
        to="john@smith.com"
    )
    reference = uuid.uuid4()

    mocker.patch('app.uuid.uuid4', return_value=reference)
    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.aws_ses_client.send_email')
    mocker.patch('app.aws_ses_client.get_name', return_value="ses")
    mocker.patch('app.celery.research_mode_tasks.send_email_response.apply_async')

    sample_service.research_mode = True
    notify_db.session.add(sample_service)
    notify_db.session.commit()

    notification_id = uuid.uuid4()

    now = datetime.utcnow()
    send_email(
        sample_service.id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )
    assert not aws_ses_client.send_email.called
    send_email_response.apply_async.assert_called_once_with(
        ('ses', str(reference), 'john@smith.com'), queue="research-mode"
    )

    persisted_notification = Notification.query.filter_by(id=notification_id).one()
    assert persisted_notification.id == notification_id
    assert persisted_notification.to == 'john@smith.com'
    assert persisted_notification.template_id == sample_email_template.id
    assert persisted_notification.status == 'sending'
    assert persisted_notification.sent_at > now
    assert persisted_notification.created_at == now
    assert persisted_notification.sent_by == 'ses'
    assert persisted_notification.reference == str(reference)


def test_should_call_send_not_update_provider_email_stats_if_research_mode(
        notify_db,
        sample_service,
        sample_email_template,
        ses_provider,
        mocker):
    notification = _notification_json(
        sample_email_template,
        to="john@smith.com"
    )

    reference = uuid.uuid4()

    mocker.patch('app.uuid.uuid4', return_value=reference)
    mocker.patch('app.encryption.decrypt', return_value=notification)
    mocker.patch('app.aws_ses_client.send_email')
    mocker.patch('app.aws_ses_client.get_name', return_value="ses")
    mocker.patch('app.celery.research_mode_tasks.send_email_response.apply_async')

    sample_service.research_mode = True
    notify_db.session.add(sample_service)
    notify_db.session.commit()

    assert not get_provider_statistics(
        sample_email_template.service,
        providers=[ses_provider.identifier]).first()

    notification_id = uuid.uuid4()
    now = datetime.utcnow()
    send_email(
        sample_service.id,
        notification_id,
        "encrypted-in-reality",
        now.strftime(DATETIME_FORMAT)
    )
    assert not aws_ses_client.send_email.called
    send_email_response.apply_async.assert_called_once_with(
        ('ses', str(reference), 'john@smith.com'), queue="research-mode"
    )

    assert not get_provider_statistics(
        sample_email_template.service,
        providers=[ses_provider.identifier]).first()


def test_email_template_personalisation_persisted(sample_email_template_with_placeholders, mocker):
    encrypted_notification = encryption.encrypt(_notification_json(
        sample_email_template_with_placeholders,
        "my_email@my_email.com",
        {"name": "Jo"},
        row_number=1))
    mocker.patch('app.statsd_client.incr')
    mocker.patch('app.statsd_client.timing_with_dates')
    mocker.patch('app.statsd_client.timing')
    mocker.patch('app.aws_ses_client.get_name', return_value='ses')
    mocker.patch('app.aws_ses_client.send_email', return_value='ses')

    notification_id = uuid.uuid4()

    send_email(
        sample_email_template_with_placeholders.service_id,
        notification_id,
        encrypted_notification,
        datetime.utcnow().strftime(DATETIME_FORMAT)
    )

    persisted_notification = Notification.query.filter_by(id=notification_id).one()

    assert persisted_notification.id == notification_id
    assert persisted_notification.personalisation == {"name": "Jo"}
    # personalisation data is encrypted in db
    assert persisted_notification._personalisation == encryption.encrypt({"name": "Jo"})


def test_sms_template_personalisation_persisted(sample_template_with_placeholders, mocker):

    encrypted_notification = encryption.encrypt(_notification_json(sample_template_with_placeholders,
                                                to="+447234123123", personalisation={"name": "Jo"}))
    mocker.patch('app.statsd_client.incr')
    mocker.patch('app.statsd_client.timing_with_dates')
    mocker.patch('app.statsd_client.timing')
    mocker.patch('app.celery.provider_tasks.send_sms_to_provider.apply_async')

    notification_id = uuid.uuid4()

    send_sms(
        sample_template_with_placeholders.service_id,
        notification_id,
        encrypted_notification,
        datetime.utcnow().strftime(DATETIME_FORMAT)
    )

    provider_tasks.send_sms_to_provider.apply_async.assert_called_once_with(
        (sample_template_with_placeholders.service.id,
         notification_id,
         encrypted_notification),
        queue="sms"
    )
    persisted_notification = Notification.query.filter_by(id=notification_id).one()

    assert persisted_notification.id == notification_id
    assert persisted_notification.to == '+447234123123'
    assert persisted_notification.personalisation == {"name": "Jo"}
    # personalisation data is encrypted in db
    assert persisted_notification._personalisation == encryption.encrypt({"name": "Jo"})
