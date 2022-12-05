import boto3
from botocore.exceptions import ClientError
from cloudlift.exceptions import UnrecoverableException
from cloudlift.config.logging import log_err


def check_sns_topic_exists(topic_name, environment):
    session = boto3.session.Session()
    sns_client = session.client('sns')
    try:
        sns_client.get_topic_attributes(TopicArn=topic_name)
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'NotFound':
            raise UnrecoverableException(
                "Unable to find SNS topic {topic_name} in {environment} environment".format(**locals()))
        else:
            raise UnrecoverableException(e.response['Error']['Message'])
