import json
import time
import boto3
import os

ECS = boto3.client('ecs')
ASG = boto3.client('autoscaling')
SNS = boto3.client('sns')
CW = boto3.client('cloudwatch')


def find_ecs_instance_info(instance_id, cluster_name):
    paginator = ECS.get_paginator('list_container_instances')
    for list_resp in paginator.paginate(cluster=cluster_name):
        arns = list_resp['containerInstanceArns']
        desc_resp = ECS.describe_container_instances(cluster=cluster_name,
                                                     containerInstances=arns)
        for container_instance in desc_resp['containerInstances']:
            if container_instance['ec2InstanceId'] != instance_id:
                continue
            print('Found instance: id=%s, arn=%s, status=%s, runningTasksCount=%s' %
                  (instance_id, container_instance['containerInstanceArn'],
                   container_instance['status'], container_instance['runningTasksCount']))
            return (container_instance['containerInstanceArn'],
                    container_instance['status'], container_instance['runningTasksCount'])
    return None, None, 0


def instance_has_running_tasks(instance_id, cluster_name):
    (instance_arn, container_status, running_tasks) = find_ecs_instance_info(
        instance_id, cluster_name)
    if instance_arn is None:
        print('Could not find instance ID %s. Letting autoscaling kill the instance.' %
              (instance_id))
        return False
    if container_status != 'DRAINING':
        print('Setting container instance %s (%s) to DRAINING' %
              (instance_id, instance_arn))
        ECS.update_container_instances_state(cluster=cluster_name,
                                             containerInstances=[instance_arn],
                                             status='DRAINING')
    return running_tasks > 0


def lambda_handler(event, context):
    msg = json.loads(event['Records'][0]['Sns']['Message'])
    print("Event: ", msg)
    if 'LifecycleTransition' not in msg.keys() or \
            msg['LifecycleTransition'].find('autoscaling:EC2_INSTANCE_TERMINATING') == -1:
        print('Exiting since the lifecycle transition is not EC2_INSTANCE_TERMINATING.')
        return
    if instance_has_running_tasks(msg['EC2InstanceId'], msg['NotificationMetadata']):
        print('Tasks are still running on instance %s; posting msg to SNS topic %s' %
              (msg['EC2InstanceId'], event['Records'][0]['Sns']['TopicArn']))
        time.sleep(5)
        sns_resp = SNS.publish(TopicArn=event['Records'][0]['Sns']['TopicArn'],
                               Message=json.dumps(msg),
                               Subject='Publishing SNS msg to invoke Lambda again.')
        print('Posted msg %s to SNS topic.' % (sns_resp['MessageId']))
    else:
        print('No tasks are running on instance %s; setting lifecycle to complete' %
              (msg['EC2InstanceId']))
        ASG.complete_lifecycle_action(LifecycleHookName=msg['LifecycleHookName'],
                                      AutoScalingGroupName=msg['AutoScalingGroupName'],
                                      LifecycleActionResult='CONTINUE',
                                      InstanceId=msg['EC2InstanceId'])
        if msg['NotificationMetadata'] == 'cluster-production':
            alarm_name = 'ecs_agent_alarm_' + msg['EC2InstanceId']
            response = CW.delete_alarms(AlarmNames=[alarm_name])
            print('Alarm %s deleted' % alarm_name)
