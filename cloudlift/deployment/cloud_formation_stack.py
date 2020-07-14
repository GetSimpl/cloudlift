from cloudlift.config.region import (get_resource_for,
                                     get_service_templates_bucket_for_environment,
                                     get_region_for_environment)

from tempfile import NamedTemporaryFile
from cloudlift.config.logging import log_intent

TEMPLATE_BODY_LIMIT = 51200


def prepare_stack_options_for_template(template_body, environment, stack_name):
    options = {}
    if len(template_body) <= TEMPLATE_BODY_LIMIT:
        options['TemplateBody'] = template_body
    else:
        s3 = get_resource_for('s3', environment)
        bucket_name = get_service_templates_bucket_for_environment(environment)

        if not bucket_name:
            from cloudlift.exceptions import UnrecoverableException
            raise UnrecoverableException(
                'Configure "service_templates_bucket" in environment configuration to apply changes')

        bucket = s3.Bucket(bucket_name)
        region = get_region_for_environment(environment)

        if bucket not in s3.buckets.all():
            bucket.create(
                ACL='private',
                Bucket=bucket_name,
                CreateBucketConfiguration={
                    'LocationConstraint': region,
                }
            )
            s3.BucketVersioning(bucket_name).enable()

        with NamedTemporaryFile() as f:
            f.write(template_body.encode())
            path = '{}/{}.template'.format(environment, stack_name)
            bucket.upload_file(f.name, path)

            template_url = 'https://s3-{}.amazonaws.com/{}/{}'.format(region, bucket_name, path)

            log_intent('Using S3 URL from deploying stack: {}'.format(template_url))

            options['TemplateURL'] = template_url

    return options
