FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME = "fluentbit-firelens-sidecar"
logging_json_schema = {
    "oneOf": [
        {"type": "string", "pattern": "^(awslogs|awsfirelens|null)$"},
        {"type": "null"},
    ]
}
