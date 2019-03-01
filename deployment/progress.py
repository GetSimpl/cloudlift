from deployment.logging import log_intent, log_intent_err


def get_stack_events(client, stack_name):
    try:
        return sorted(
            client.describe_stack_events(
                StackName=stack_name
            )['StackEvents'], key=lambda k: k['Timestamp'])
    except Exception:
        return []


def print_new_events(all_events, existing_events):
    new_events = [evnt for evnt in all_events if evnt not in existing_events]
    for event in new_events:
        update = "%s: Resource: %s\t\tStatus: %s" % (
            event['Timestamp'],
            event['LogicalResourceId'],
            event['ResourceStatus']
        )
        if 'ResourceStatusReason' in event:
            update += "\t\tReason: %s" % event['ResourceStatusReason']
        if "ERROR" in update or "FAIL" in update:
            log_intent_err(update)
        else:
            log_intent(update)
