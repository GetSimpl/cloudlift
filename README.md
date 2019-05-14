# Cloudlift

Cloudlift is built by Simpl developers to make it easier to launch dockerized
services in AWS ECS.

Cloudlift is a command-line tool for dockerized services to be deployed in AWS
ECS. It's very simple to use. That's possible because this is heavily
opinionated. Under the hood, it is a wrapper to AWS cloudformation templates. On
creating/udpating a service or a cluster this creates/updates a cloudformation
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

### 2. Download and Install cloudlift

```sh
git clone git@github.com:GetSimpl/cloudlift.git
cd cloudlift
./install-cloudlift.sh
```

### 2. Configure AWS

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

#### 1. Upload configuration to Parameter Store

During create_service and deployment `cloudlift` pulls the config from AWS
Parameter Store to apply it on the task definition. Configurations are stored in
path with the convention `/<environment>/<service>/<key>`

```sh
cloudlift edit_config -e <environment-name>
```

  _NOTE_: This is *not* required for every deployment. It's required only when
  config needs to be changed.

#### 2. Create service

In the repository for the application, run -

```sh
  cloudlift create_service -e <environment-name>
```

This opens the `VISUAL` editor with default config similar to -

```json
  {
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
              "memory_reservation": 1000
          }
      }
  }
```

Definitions -

`services`: Map of all ECS services with configuration for current application

`command`: Override command in Dockerfile

`http_interface`: Configuration for HTTP interface if required, do not include
this if the services does not require a HTTP interface

`container_port`: Port in which the process is exposed inside container

`internal`: Scheme of loadbalancer. If internal, the loadbalancer is accessible
only within the VPC

`restrict_access_to`: List of CIDR to which HTTP interface is restricted to.

`memory_reservation`: Memory size reserved for each task in MBs. This is a soft
limit, i.e. at least this much memory will be available, and upto whatever
memory is free in running container instance.

#### 3. Deploy service

```sh
  cloudlift deploy_service -e <environment-name>
```

### 6. Starting shell on container instance for service

You can start a shell on a container instance which is running a task for given
application using the `start_session` command. One pre-requisite for this is
installing the session manager plugin for `awscli`. To install session manager
plugin follow the [guide](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html#install-plugin-macos)

```sh
  cloudlift start_session -e <environment-name>
```

MFA code can be passed as parameter `--mfa` or you will be prompted to enter
the MFA code.

## Contributing to cloudlift

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
