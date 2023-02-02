from cloudlift.config.account import get_user_id

def highlight_production():
    print('''\033[91m
********************************
**          Careful!          **
**    You're on PRODUCTION    **
********************************\033[0m
''')

def highlight_user_account_details():
    username, account = get_user_id()
    print('''\033[93m 
******* Using Aws account {account} and Username {username} *******\033[0m
'''.format(**locals()))
    
