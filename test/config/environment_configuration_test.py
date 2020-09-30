import boto3
import pytest
from moto import mock_dynamodb2

from cloudlift.config import EnvironmentConfiguration


class TestEnvironmentConfiguration(object):
    def setup_existing_params(self):
        client = boto3.resource('dynamodb')
        client.create_table(
            TableName='environment_configurations',
            AttributeDefinitions=[
                {
                    'AttributeName': 'environment',
                    'AttributeType': 'S',
                }
            ],
            KeySchema=[
                {
                    'AttributeName': 'environment',
                    'KeyType': 'HASH',
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 10,
                'WriteCapacityUnits': 10
            }
        )
        table = client.Table('environment_configurations')
        table.update_item(
            TableName='environment_configurations',
            Key={
                'environment': 'dummy-staging'
            },
            UpdateExpression='SET configuration = :configuration',
            ExpressionAttributeValues={
                ':configuration': {
                    "dummy-staging": {
                        "cluster": {
                            "instance_type": "m5.xlarge",
                            "key_name": "staging-cluster-v3",
                            "max_instances": 10,
                            "min_instances": 5
                        },
                        "environment": {
                            "notifications_arn": "arn:aws:sns:ap-south-1:725827686899:non-prod-mumbai",
                            "ssl_certificate_arn": "arn:aws:acm:ap-south-1:725827686899:certificate/380232d3-d868-4ce3-a43d-211cdfd39d26"
                        },
                        "region": "ap-south-1",
                        "vpc": {
                            "cidr": "10.30.0.0/16",
                            "nat-gateway": {
                                "elastic-ip-allocation-id": "eipalloc-05f2599c8bd8d3d28"
                            },
                            "subnets": {
                                "private": {
                                    "subnet-1": {
                                        "cidr": "10.30.4.0/22"
                                    },
                                    "subnet-2": {
                                        "cidr": "10.30.12.0/22"
                                    }
                                },
                                "public": {
                                    "subnet-1": {
                                        "cidr": "10.30.0.0/22"
                                    },
                                    "subnet-2": {
                                        "cidr": "10.30.8.0/22"
                                    }
                                }
                            }
                        }
                    }
                }
            },
            ReturnValues="UPDATED_NEW"
        )
        table.update_item(
            TableName='environment_configurations',
            Key={
                'environment': 'random-environment'
            },
            UpdateExpression='SET configuration = :configuration',
            ExpressionAttributeValues={
                ':configuration': {
                    "random-environment": {
                        "cluster": {
                            "instance_type": "m5.xlarge",
                            "key_name": "staging-cluster-v3",
                            "max_instances": 10,
                            "min_instances": 5
                        },
                        "environment": {
                            "notifications_arn": "arn:aws:sns:ap-south-1:725827686899:non-prod-mumbai",
                            "ssl_certificate_arn": "arn:aws:acm:ap-south-1:725827686899:certificate/380232d3-d868-4ce3-a43d-211cdfd39d26"
                        },
                        "region": "ap-south-1",
                        "vpc": {
                            "cidr": "10.30.0.0/16",
                            "nat-gateway": {
                                "elastic-ip-allocation-id": "eipalloc-05f2599c8bd8d3d28"
                            },
                            "subnets": {
                                "private": {
                                    "subnet-1": {
                                        "cidr": "10.30.4.0/22"
                                    },
                                    "subnet-2": {
                                        "cidr": "10.30.12.0/22"
                                    }
                                },
                                "public": {
                                    "subnet-1": {
                                        "cidr": "10.30.0.0/22"
                                    },
                                    "subnet-2": {
                                        "cidr": "10.30.8.0/22"
                                    }
                                }
                            }
                        }
                    }
                }
            },
            ReturnValues="UPDATED_NEW"
        )

    @mock_dynamodb2
    def test_initialization(self):
        self.setup_existing_params()

        store_object = EnvironmentConfiguration('dummy-staging')
        assert store_object.environment == 'dummy-staging'
        assert store_object.table is not None

    @mock_dynamodb2
    def test_get_config(self):
        self.setup_existing_params()

        store_object = EnvironmentConfiguration('dummy-staging')
        response = store_object.get_config()
        assert response == {
            "dummy-staging": {
                "cluster": {
                    "instance_type": "m5.xlarge",
                    "key_name": "staging-cluster-v3",
                    "max_instances": 10,
                    "min_instances": 5
                },
                "environment": {
                    "notifications_arn": "arn:aws:sns:ap-south-1:725827686899:non-prod-mumbai",
                    "ssl_certificate_arn": "arn:aws:acm:ap-south-1:725827686899:certificate/380232d3-d868-4ce3-a43d-211cdfd39d26"
                },
                "region": "ap-south-1",
                "vpc": {
                    "cidr": "10.30.0.0/16",
                            "nat-gateway": {
                                "elastic-ip-allocation-id": "eipalloc-05f2599c8bd8d3d28"
                            },
                    "subnets": {
                                "private": {
                                    "subnet-1": {
                                        "cidr": "10.30.4.0/22"
                                    },
                                    "subnet-2": {
                                        "cidr": "10.30.12.0/22"
                                    }
                                },
                                "public": {
                                    "subnet-1": {
                                        "cidr": "10.30.0.0/22"
                                    },
                                    "subnet-2": {
                                        "cidr": "10.30.8.0/22"
                                    }
                                }
                            }
                }
            }
        }

    @mock_dynamodb2
    def test_get_all_environments(self):
        self.setup_existing_params()

        store_object = EnvironmentConfiguration('dummy-staging')
        response = store_object.get_all_environments()
        assert response == ['dummy-staging', 'random-environment']

    @mock_dynamodb2
    def test_set_config(self):
        self.setup_existing_params()

        store_object = EnvironmentConfiguration('dummy-staging')
        get_response = store_object.get_config()

        get_response["dummy-staging"]["cluster"]["instance_type"] = "t2.large"
        get_response["dummy-staging"]["cluster"]["min_instances"] = 1
        get_response["dummy-staging"]["cluster"]["max_instances"] = 10
        store_object._set_config(get_response)
        update_response = store_object.get_config()

        assert update_response == {
            "dummy-staging": {
                "cluster": {
                    "instance_type": "t2.large",
                    "key_name": "staging-cluster-v3",
                    "max_instances": 10,
                    "min_instances": 1
                },
                "environment": {
                    "notifications_arn": "arn:aws:sns:ap-south-1:725827686899:non-prod-mumbai",
                    "ssl_certificate_arn": "arn:aws:acm:ap-south-1:725827686899:certificate/380232d3-d868-4ce3-a43d-211cdfd39d26"
                },
                "region": "ap-south-1",
                "vpc": {
                    "cidr": "10.30.0.0/16",
                        "nat-gateway": {
                            "elastic-ip-allocation-id": "eipalloc-05f2599c8bd8d3d28"
                        },
                    "subnets": {
                        "private": {
                            "subnet-1": {
                                "cidr": "10.30.4.0/22"
                            },
                            "subnet-2": {
                                "cidr": "10.30.12.0/22"
                            }
                        },
                        "public": {
                            "subnet-1": {
                                "cidr": "10.30.0.0/22"
                            },
                            "subnet-2": {
                                "cidr": "10.30.8.0/22"
                            }
                        }
                    }
                }
            }
        }
