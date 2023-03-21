import boto3
from botocore.exceptions import ClientError
from cloudlift.exceptions import UnrecoverableException
from cloudlift.config.logging import log_err
from cloudlift.config.stack import get_service_stack_name
import re

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

def check_aws_instance_type(instance_type):
    pattern = r"^((a1|c1|c3|c4|c5|c5a|c5ad|c5d|c5n|c6a|c6g|c6gd|c6gn|c6i|c6id|c7g|cc2|d2|d3|d3en|dl1|f1|g2|g3|g3s|g4ad|g4dn|g5|g5g|h1|i2|i3|i3en|i4i|im4gn|inf1|is4gen|m1|m2|m3|m4|m5|m5a|m5ad|m5d|m5dn|m5n|m5zn|m6a|m6g|m6gd|m6i|m6id|mac1|mac2|p2|p3|p3dn|p4d|r3|r4|r5|r5a|r5ad|r5b|r5d|r5dn|r5n|r6a|r6g|r6gd|r6i|r6id|t1|t2|t3|t3a|t4g|trn1|u-12tb1|u-3tb1|u-6tb1|u-9tb1|vt1|x1|x1e|x2gd|x2idn|x2iedn|x2iezn|z1d)\.(10xlarge|112xlarge|12xlarge|16xlarge|18xlarge|24xlarge|2xlarge|32xlarge|3xlarge|48xlarge|4xlarge|56xlarge|6xlarge|8xlarge|9xlarge|large|medium|metal|micro|nano|small|xlarge))"
    instance_type = instance_type.split(",")
    for i in instance_type:
        if re.match(pattern, i):
            continue
        else:
            return False, i
    return True, ""