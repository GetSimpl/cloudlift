import time


def wait_until(predicate, timeout, period=1, *args, **kwargs):
    mustend = time.time() + timeout
    while time.time() < mustend:
        if predicate(*args, **kwargs):
            return True
        print("sleeping and gonna retry...")
        time.sleep(period)
    return False
