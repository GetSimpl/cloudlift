import datetime

from cfn_flip import to_json
from mock import patch

from cloudlift.config import ServiceConfiguration
from cloudlift.deployment.cluster_template_generator import ClusterTemplateGenerator



def mocked_environment_config(cls, *args, **kwargs):
    return {
            "demo": {
            "cluster": {
                "instance_type": "t3a.micro",
                "key_name": "praveen-test",
                "max_instances": 2,
                "min_instances": 1
            },
            "draining": {
                "heartbeat_timeout": 300,
                "lifecycle_hook_name": "DemoTest",
                "topic_name": "DemoTest"
            },
            "environment": {
                "notifications_arn": "arn:aws:sns:ap-south-1:259042324395:Praveen",
                "ssl_certificate_arn": "arn:aws:acm:ap-south-1:259042324395:certificate/09d771d0-24d3-45d2-8e40-2237f12bea6a"
            },
            "region": "ap-south-1",
            "vpc": {
                "cidr": "10.7.0.0/16",
                "nat-gateway": {
                "elastic-ip-allocation-id": "eipalloc-0103733acf336d725"
                },
                "subnets": {
                "private": {
                    "subnet-1": {
                    "cidr": "10.7.8.0/22"
                    },
                    "subnet-2": {
                    "cidr": "10.7.12.0/22"
                    }
                },
                "public": {
                    "subnet-1": {
                    "cidr": "10.7.0.0/22"
                    },
                    "subnet-2": {
                    "cidr": "10.7.4.0/22"
                    }
                }
                }
            }
        }
    }

class TestServiceTemplateGenerator(object):
    def test_environment_creation(self):
        en = ClusterTemplateGenerator("demo", mocked_environment_config)