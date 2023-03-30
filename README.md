# Cloudlift

Cloudlift is built by Simpl developers to make it easier to launch dockerized
services in AWS ECS.

Cloudlift is a command-line tool for dockerized services to be deployed in AWS
ECS. It's very simple to use. That's possible because this is heavily
opinionated. Under the hood, it is a wrapper to AWS cloudformation templates. On
creating/updating a service or a cluster this creates/updates a cloudformation
in AWS.

## Demo videos

- [Create Environment](https://asciinema.org/a/evsaZvW86qff0InxNlzLPMtb6)
- [Create Service](https://asciinema.org/a/RaZb81VDmrnWg8qckWKAm98Bn)
- [Deploy Service with image build](https://asciinema.org/a/j4A2DBjLPadbwJPvwiT6W1c2N)
- [Deploy Service](https://asciinema.org/a/FUUJ3U2gm7U1yCcTCGjTiGBbp)

## Installing cloudlift

### 1. Pre-requisites

- pip
```sh
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py | python get-pip.py
```

### 2. Install cloudlift

```sh
pip install cloudlift
```


### 3. Configure AWS

```perl
aws configure
```

Enter the AWS Access Key ID, AWS Secret Access Key. You can find instructions
here on how to get Access Key ID and Secret Access Key here at
http://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html

#### Using AWS Profiles

If you are using [AWS profiles](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-profiles.html), set the desired profile name in the environment before invoking Cloudlift.

```sh
AWS_DEFAULT_PROFILE=<profile name> cloudlift <command>
```

OR

```sh
export AWS_DEFAULT_PROFILE=<profile name>
cloudlift <command>
cloudlift <command>
```

## Usage

### Create a new environment

Create a new environment for services to be deployed. Cloudlift creates a new
VPC for the given CIDR and sets up the required networking infrastructure for
services to run in ECS.

```sh
cloudlift create_environment -e <environment-name>
```

This starts a prompt for required details to create an environment, which
includes -

- AWS region for the environment
- VPC CIDR
- NAT Elastic IP allocation ID
- 2 Public Subnet CIDRs
- 2 Private Subnet CIDRs
- Minimum instances for cluster
- Maximum instances for cluster
- SSM parameter path of Custom AMI ID
- SSH key name
- SNS ARN for notifications
- AWS ACM ARN for SSL certificate

Once the configuration is saved, this is opened in the default `VISUAL` editor.
Here configurations can be changed if required.

### Update an environment

```sh
cloudlift update_environment -e <environment-name>
```

This opens the environment configuration in the `VISUAL` editor. Update this to
make changes to the environment.

### Create a new service

### Object Structure
The configuration object is structured as follows:

```json
{
    "notifications_arn": "string",
    "services": {
        "Test123": {
            "command": "string/null",
            "custom_metrics": {
                "metrics_port": "string",
                "metrics_path": "string"
            },
            "http_interface": {
                "container_port": "number",
                "internal": "boolean",
                "restrict_access_to": ["string", "string"]
            },
            "volume": {
                "efs_id" : "string",
                "efs_directory_path" : "string",
                "container_path" : "string"
            },
            "memory_reservation": "number",
            "logging": "string/null"
        }
    }
}
```
### Required Fields

The following fields are required in the configuration object:

- `notifications_arn`: A string representing the Amazon Resource Name (ARN) of the SNS topic to which notifications will be sent.

- `services`: An object representing the services to be configured. The keys of this object are the names of the services, and the values are objects containing configuration information for each service.


### Service Configuration

Each service object must contain the following fields:

- `command`: A string or null value representing the command to be run in the Docker container. If this field is null, the command specified in the Dockerfile will be used.

- `memory_reservation`: A number representing the soft memory limit for the container. The hard limit will automatically be set to 1.5 times the soft limit.

In addition, a service object may contain any of the following optional fields:

- `custom_metrics`: An object containing configuration information for exporting custom metrics to a Prometheus server. This field is only used if custom metrics are required.


    > **NOTE:** If you use custom metrics, Your ECS container Network mode will be `awsvpc`. 

    > **⚠ WARNING:** If you are adding custom metrics to your existing service, there will be a downtime.

  - `metrics_port`: A string representing the port number on which custom metrics are exported.
  
  - `metrics_path`: A string representing the path on which custom metrics are exported.

- `http_interface`: An object containing configuration information for setting up an Application Load Balancer (ALB) for the service. This field is only used if an ALB is required.

  - `container_port`: A number representing the port number on which the service is running inside the container.
  
  - `internal`: A boolean value indicating whether the ALB should be internal. If set to false, the ALB will be public.
  
  - `restrict_access_to`: An array of strings representing the IP addresses that should be allowed to access the ALB.

- `volume`: An object containing configuration information for mounting an Amazon Elastic File System (EFS) volume to the service. This field is only used if an EFS volume is required.

  - `efs_id`: A string representing the ID of the EFS volume to be mounted.
  
  - `efs_directory_path`: A string representing the directory path on the EFS volume to be mounted.
  
  - `container_path`: A string representing the mount path inside the container.

- `logging`: A string or null value representing the log driver to be used. Valid options are "fluentd", "awslogs", or null. If this field is null, the default log driver (CloudWatch Logs) will be used.


### 1. Upload configuration to Parameter Store

During create_service and deployment `cloudlift` pulls the config from AWS
Parameter Store to apply it on the task definition. Configurations are stored in
path with the convention `/<environment>/<service>/<key>`

```sh
cloudlift edit_config -e <environment-name>
```

  _NOTE_: This is *not* required for every deployment. It's required only when
  config needs to be changed.

### 2. Create service

In the repository for the application, run -

```sh
  cloudlift create_service -e <environment-name>
```

This opens the `VISUAL` editor with default config similar to -

```json
  {
      "notifications_arn": "<SNS Topic ARN>",
      "services": {
          "Test123": {
              "command": null,
              "http_interface": {
                  "container_port": 80,
                  "internal": false,
                  "restrict_access_to": [
                      "0.0.0.0/0"
                  ]
              },
              "memory_reservation": 100
          }
      }
  }
```
### 3. Deploy service

This command build the image (only if the version is unavailable in ECR), pushes to ECR and updates the ECS 
service task definition. It supports `--build-arg` argument of `docker build` command as well to pass
custom build time arguments

```sh
  cloudlift deploy_service -e <environment-name>
```

For example, you can pass your SSH key as a build argument to docker build

```sh
  cloudlift deploy_service --build-arg SSH_KEY "\"`cat ~/.ssh/id_rsa`\"" -e <environment-name>
```
This example is bit comprehensive to show
- it can execute shell commands with "`".
- It's wrapped with double quotes to avoid line-breaks in SSH keys breaking the command.

### 4. Starting shell on container instance for service

You can start a shell on a container instance which is running a task for given
application using the `start_session` command. One pre-requisite for this is
installing the session manager plugin for `awscli`. To install session manager
plugin follow the [guide](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html#install-plugin-macos)

```sh
  cloudlift start_session -e <environment-name>
```

MFA code can be passed as parameter `--mfa` or you will be prompted to enter
the MFA code.


## Example

### 1. Service configuration:
```json
{
  "notifications_arn": "arn:aws:sns:us-east-1:123456789012:MyTopic",
  "services": {
    "Test123": {
      "command": null,
      "custom_metrics": {
        "metrics_port": "8080",
        "metrics_path": "/metrics"
      },
      "http_interface": {
        "container_port": 3000,
        "internal": false,
        "restrict_access_to": ["192.0.2.0/24", "198.51.100.0/24"]
      },
      "volume": {
        "efs_id": "fs-0123456789abcdef",
        "efs_directory_path": "/mydata",
        "container_path": "/data"
      },
      "memory_reservation": 256,
      "logging": "fluentd"
    }
  }
}
```
In this example, we are configuring a service named Test123. The service has the following configuration:

- `command`: The command to be run in the Docker container is not specified, so the command specified in the Dockerfile will be used.
- `custom_metrics`: Custom metrics will be exported to a Prometheus server running on port 8080, with the metrics available at the path "/metrics".
- `http_interface`: An Application Load Balancer (ALB) will be set up for the service on port 3000. The ALB will be public and will allow access only from the IP addresses in the restrict_access_to array.
- `volume`: An Amazon Elastic File System (EFS) volume with ID fs-0123456789abcdef will be mounted to the service. The volume will be mounted at the directory path "/mydata" on the EFS volume, and at the path "/data" inside the container.
- `memory_reservation`: The soft memory limit for the container is set to 256 MB, so the hard limit will be automatically set to 384 MB.
- `logging`: Logs will be sent to a Fluentd log driver.

### 2. Service configuration with custom metrics:
```json
  {
      "notifications_arn": "<SNS Topic ARN>",
      "services": {
          "Test123": {
              "command": null,
              "custom_metrics": {
                  "metrics_port": "8005",
                  "metrics_path": "/metrics"
              },
              "http_interface": {
                  "container_port": 80,
                  "internal": false,
                  "restrict_access_to": [
                      "0.0.0.0/0"
                  ]
              },
              "memory_reservation": 100
          }
      }
  }
```
### 3. Service configuration with volume mount:
```json
  {
      "notifications_arn": "<SNS Topic ARN>",
      "services": {
          "Test123": {
              "command": null,
              "volume": {
                  "efs_id" : "fs-XXXXXXX",
                  "efs_directory_path" : "/",
                  "container_path" : "/"
              },
              "http_interface": {
                  "container_port": 80,
                  "internal": false,
                  "restrict_access_to": [
                      "0.0.0.0/0"
                  ]
              },
              "memory_reservation": 100
          }
      }
  }
```
### 4. Service configuration with http interface only:
```json
  {
      "notifications_arn": "<SNS Topic ARN>",
      "services": {
          "Test123": {
              "command": null,
              "http_interface": {
                  "container_port": 80,
                  "internal": false,
                  "restrict_access_to": [
                      "0.0.0.0/0"
                  ]
              },
              "memory_reservation": 100
          }
      }
  }
```
### 5. Service configuration with http interface without AWS CW logging.

> **_NOTE:_** Do not use `logging: null` in production. Once container  gets deleted all logs will be lost. Logging configuration should be one of the following: `awslog`, `fluentd`,`null`

```json
  {
      "notifications_arn": "<SNS Topic ARN>",
      "services": {
          "Test123": {
              "command": null,
              "http_interface": {
                  "container_port": 80,
                  "internal": false,
                  "restrict_access_to": [
                      "0.0.0.0/0"
                  ]
              },
              "memory_reservation": 100,
              "logging": null
          }
      }
  }
```

## Contributing to cloudlift

### Setup

#### Use the latest git master 

```sh
git clone git@github.com:GetSimpl/cloudlift.git
cd cloudlift
./install-cloudlift.sh
```


To ensure the tests use the development version and not the installed version run (refer [here](https://stackoverflow.com/a/20972950/227705))

```
pip install -e .
```

### Tests

First level of tests have been added to assert cloudformation template generated
vs expected one.

```sh
py.test test/deployment/
```

To run high level integration tests

```sh
pytest -s test/test_cloudlift.py
```

This tests expects to have an access to AWS console.
Since there's no extensive test coverage, it's better to manually test the
impacted areas whenever there's a code change.
