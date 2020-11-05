import boto3
import botocore
from flask import current_app
from time import monotonic
from notifications_utils.recipients import InvalidEmailError
import unicodedata

from app.clients import STATISTICS_DELIVERED, STATISTICS_FAILURE
from app.clients.email import (EmailClientException, EmailClient)
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.header import Header

ses_response_map = {
    'Permanent': {
        "message": 'Hard bounced',
        "success": False,
        "notification_status": 'permanent-failure',
        "notification_statistics_status": STATISTICS_FAILURE
    },
    'Temporary': {
        "message": 'Soft bounced',
        "success": False,
        "notification_status": 'temporary-failure',
        "notification_statistics_status": STATISTICS_FAILURE
    },
    'Delivery': {
        "message": 'Delivered',
        "success": True,
        "notification_status": 'delivered',
        "notification_statistics_status": STATISTICS_DELIVERED
    },
    'Complaint': {
        "message": 'Complaint',
        "success": True,
        "notification_status": 'delivered',
        "notification_statistics_status": STATISTICS_DELIVERED
    }
}


def get_aws_responses(status):
    return ses_response_map[status]


class AwsSesClientException(EmailClientException):
    pass


class AwsSesClient(EmailClient):
    '''
    Amazon SES email client.
    '''

    def init_app(self, region, statsd_client, *args, **kwargs):
        self._client = boto3.client('ses', region_name=region)
        super(AwsSesClient, self).__init__(*args, **kwargs)
        self.name = 'ses'
        self.statsd_client = statsd_client
        self.charset = 'utf-8'

    def get_name(self):
        return self.name

    def send_email(self,
                   source,
                   sending_domain,
                   to_addresses,
                   subject,
                   body,
                   html_body='',
                   reply_to_address=None,
                   attachments=[],
                   importance=None,
                   cc_addresses=None):
        try:
            aws_ses_owner_account = current_app.config['AWS_SES_OWNER_ACCOUNT']
            aws_ses_arn = 'arn:aws:ses:{}:{}:identity/{}'.format(current_app.config['AWS_SES_REGION'], aws_ses_owner_account,
                sending_domain) if aws_ses_owner_account else None
            if isinstance(to_addresses, str):
                to_addresses = [to_addresses]
            if isinstance(cc_addresses, str):
                cc_addresses = [cc_addresses]

            source = unicodedata.normalize('NFKD', source)
            friendly_name, match_string, from_address = source.partition("<")
            friendly_name = friendly_name.replace('"', '')
            h = Header(friendly_name, 'utf-8')
            encoded_friendly_name = h.encode()
            encoded_source = '{} {}{}'.format(encoded_friendly_name, match_string, from_address)

            reply_to_addresses = [reply_to_address] if reply_to_address else []

            multipart_content_subtype = 'alternative' if html_body else 'mixed'
            msg = MIMEMultipart(multipart_content_subtype)
            msg['Subject'] = subject
            msg['From'] = encoded_source
            msg['To'] = ",".join([punycode_encode_email(addr) for addr in to_addresses])
            if aws_ses_arn:
                msg.add_header('X-SES-SOURCE-ARN', aws_ses_arn)
                msg.add_header('X-SES-FROM-ARN', aws_ses_arn)
            if importance:
                msg.add_header('importance', importance)
            if cc_addresses:
                msg['CC'] = ",".join([punycode_encode_email(addr) for addr in cc_addresses])
            if reply_to_addresses != []:
                msg.add_header('reply-to', ",".join([punycode_encode_email(addr) for addr in reply_to_addresses]))
            part = MIMEText(body.encode(self.charset), 'plain', self.charset)
            msg.attach(part)

            if html_body:
                part = MIMEText(html_body.encode(self.charset), 'html', self.charset)
                msg.attach(part)

            for attachment in attachments or []:
                part = MIMEApplication(attachment["data"])
                part.add_header('Content-Disposition', 'attachment', filename=attachment["name"])
                msg.attach(part)

            start_time = monotonic()
            response = self._client.send_raw_email(
                Source=source,
                RawMessage={'Data': msg.as_string()}
            )
        except botocore.exceptions.ClientError as e:
            self.statsd_client.incr("clients.ses.error")

            # http://docs.aws.amazon.com/ses/latest/DeveloperGuide/api-error-codes.html
            if e.response['Error']['Code'] == 'InvalidParameterValue':
                raise InvalidEmailError('email: "{}" message: "{}"'.format(
                    to_addresses[0],
                    e.response['Error']['Message']
                ))
            else:
                self.statsd_client.incr("clients.ses.error")
                raise AwsSesClientException(str(e))
        except Exception as e:
            self.statsd_client.incr("clients.ses.error")
            raise AwsSesClientException(str(e))
        else:
            elapsed_time = monotonic() - start_time
            current_app.logger.info("AWS SES request finished in {}".format(elapsed_time))
            self.statsd_client.timing("clients.ses.request-time", elapsed_time)
            self.statsd_client.incr("clients.ses.success")
            return response['MessageId']


def punycode_encode_email(email_address):
    # only the hostname should ever be punycode encoded.
    local, hostname = email_address.split('@')
    return '{}@{}'.format(local, hostname.encode('idna').decode('utf-8'))
