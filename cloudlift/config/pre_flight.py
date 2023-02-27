import boto3
from botocore.exceptions import ClientError
from cloudlift.exceptions import UnrecoverableException
from cloudlift.config.logging import log_err
from cloudlift.config.stack import get_service_stack_name

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
        
def check_stack_exists(name, environment, cmd):
    session = boto3.session.Session()
    cloudformation_client = session.client('cloudformation')
    try:
        stack_name = get_service_stack_name(environment, name)
        cloudformation_client.describe_stacks(StackName=stack_name)
        if cmd == 'create':
            raise UnrecoverableException(
                "CloudFormation stack {name} in {environment} environment already exists.".format(**locals()))
        elif cmd == 'update':
            return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ValidationError' and cmd == 'create':
            return True
        elif e.response['Error']['Code'] == 'ValidationError' and cmd == 'update':
            raise UnrecoverableException(
                "CloudFormation stack {name} in {environment} environment does not exist.".format(**locals()))
        else:
            raise UnrecoverableException(e.response['Error']['Message'])