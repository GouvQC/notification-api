import clx.xms
import requests
import phonenumbers
from time import monotonic
import unicodedata
from app.clients.sms import SmsClient

sinch_response_map = {
    'Dispatched': 'created',
    'Queued': 'sending',
    'Delivered': 'delivered',
    'Failed': 'permanent-failure',
    'Rejected': 'permanent-failure',
    'Aborted': 'permanent-failure',
    'Expired': 'permanent-failure',
    'Unknown': 'technical-failure',
}


def get_sinch_responses(status):
    return sinch_response_map[status]


class SinchSMSClient(SmsClient):
    '''
    Sinch sms client
    '''
    def __init__(self,
                 service_plan_id=None,
                 token=None,
                 *args, **kwargs):
        super(SinchSMSClient, self).__init__(*args, **kwargs)
        self._service_plan_id = service_plan_id
        self._token = token
        self._client = clx.xms.Client(service_plan_id, token, 'https://ca.sms.api.sinch.com/xms')

    def init_app(self, logger, callback_notify_url_host, statsd_client, *args, **kwargs):
        self.logger = logger
        self.statsd_client = statsd_client
        self._callback_notify_url_host = callback_notify_url_host

    @property
    def name(self):
        return 'sinch'

    def get_name(self):
        return self.name

    def send_sms(self, to, content, reference, sender=None):
        matched = False

        for match in phonenumbers.PhoneNumberMatcher(to, "US"):
            matched = True
            to = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)

            start_time = monotonic()
            callback_url = "{}/notifications/sms/sinch/{}".format(
                self._callback_notify_url_host, reference) if self._callback_notify_url_host else ""
            create = clx.xms.api.MtBatchTextSmsCreate()
            create.sender = sender
            create.recipients = {to}
            create.body = unicodedata.normalize('NFKD', content)
            create.client_reference = reference
            create.delivery_report = "per_recipient"
            create.callback_url = callback_url
            try:
                batch = self._client.create_batch(create)
                self.logger.info("Sinch send SMS request for {} succeeded: {}".format(reference, batch.batch_id))
            except (requests.exceptions.RequestException, clx.xms.exceptions.ApiException) as ex:
                self.statsd_client.incr("clients.sinch.error")
                self.logger.error("Failed to communicate with XMS: %s" % str(ex))
                raise ex
            except Exception as e:
                self.statsd_client.incr("clients.sinch.error")
                self.logger.error("Sinch send SMS request for {} failed".format(reference))
                raise e
            finally:
                elapsed_time = monotonic() - start_time
                self.logger.info("Sinch send SMS request for {} finished in {}".format(reference, elapsed_time))
                self.statsd_client.timing("clients.sinch.request-time", elapsed_time)
                self.statsd_client.incr("clients.sinch.success")
                return batch.batch_id

        if not matched:
            self.statsd_client.incr("clients.sinch.error")
            self.logger.error("No valid numbers found in {}".format(to))
            raise ValueError("No valid numbers found for SMS delivery")
