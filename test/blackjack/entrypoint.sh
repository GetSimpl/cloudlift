#!/bin/bash

set -eu -o pipefail

socat -v -T1 tcp4-l:1026,reuseaddr,fork "system:sed -ur -e \'s/^/no /\'"  &  # Careful quoting, NLB health check
socat -v -T1 udp4-l:1025,reuseaddr,fork "system:sed -ur -e \'s/^/no /\'"     # Careful quoting
