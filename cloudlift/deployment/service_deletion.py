from cloudlift.config import get_client_for, get_service_stack_name
from cloudlift.config import ParameterStore
from cloudlift.config.logging import log, log_err
from cloudlift.exceptions import UnrecoverableException


class ServiceDeletion(object):
    '''
        Delete CloudFormation stack for ECS service and related dependencies
    '''
    def __init__(self, name, environment):
        self.name = name
        self.environment = environment
        self.stack_name = get_service_stack_name(environment, name)
        self.client = get_client_for('cloudformation', self.environment)
        self.client_iam = get_client_for('iam', self.environment)
        self.init_stack_info()

    def init_stack_info(self):
        self.stack_name = get_service_stack_name(self.environment, self.name)
        try:
            self.stack_resource = self.client.describe_stack_resources(StackName=self.stack_name)['StackResources']
        except Exception as e:
            raise UnrecoverableException(e)

    def delete_stack(self):
        log("Deleting CloudFormation stack " + self.stack_name + " ...")
        self.delete_iam_role_policy()
        try:
            self.client.delete_stack(StackName=self.stack_name)
            self.delete_ssm_parameter()
            return True
        except Exception as e:
            return UnrecoverableException(e)
        
    def delete_iam_role_policy(self):
        
        for resource in self.stack_resource:
            if resource['LogicalResourceId'].endswith("Role") and resource['LogicalResourceId'] != "ECSServiceRole":
                log("Deleting IAM Role Policy for "| resource['LogicalResourceId'] + " resource")
                try:
                    policies = self.client_iam.list_attached_role_policies(RoleName=resource['PhysicalResourceId'])
                    for policy in policies['AttachedPolicies']:
                        self.client_iam.detach_role_policy(
                            RoleName=resource['PhysicalResourceId'], PolicyArn=policy['PolicyArn'])
                    print(f"All the attached policies of {resource['PhysicalResourceId']} has been removed from IAM role")
                except Exception as e:
                    raise UnrecoverableException(e)
    
    def delete_ssm_parameter(self):
        log("Deleting SSM Parameters..")
        parameter_store = ParameterStore(self.name, self.environment)
        environment_configs, environment_configs_path = parameter_store.get_existing_config()
        for k, v in environment_configs_path.items():
            try:
                self.client.delete_parameter(
                    Name=v
                )
            except Exception as e:
                print(e)
