from troposphere import Output, Ref, Template

from config import region as region_service
from config.stack import get_cluster_name


class TemplateGenerator(object):
    """This is the base class for all templates"""

    def __init__(self, env):
        self.template = Template()
        self.env = env
        self.cluster_name = get_cluster_name(env)

    def _add_stack_outputs(self):
        self.template.add_output(
            Output(
                "StackId",
                Description="The unique ID of the stack. To be supplied to \
circle CI environment variables to validate during deployment.",
                Value=Ref("AWS::StackId")
            )
        )
        self.template.add_output(
            Output(
                "StackName",
                Description="The name of the stack",
                Value=Ref('AWS::StackName')
            )
        )

    @property
    def region(self):
        return region_service.get_region_for_environment(self.env)

    @property
    def notifications_arn(self):
        return region_service.get_notifications_arn_for_environment(self.env)

    @property
    def ssl_certificate_arn(self):
        return region_service.get_ssl_certification_for_environment(self.env)
