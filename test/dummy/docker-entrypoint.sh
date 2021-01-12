#!/bin/bash -el

set -e

echo "Executing entrypoint"

if [ ! -z "${CLOUDLIFT_INJECTED_SECRETS}" ]; then
  echo "Injecting secrets to env"
  echo $CLOUDLIFT_INJECTED_SECRETS | jq -r  'to_entries | .[] | "export \(.key)=\(.value | @sh)"' > secrets.env
  source secrets.env
  rm secrets.env
  unset CLOUDLIFT_INJECTED_SECRETS
else
  echo "No secrets to inject"
fi

exec $@