'''
    Handles decimal conversion to json
    https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GettingStarted.Python.03.html
'''

import decimal
import json


class DecimalEncoder(json.JSONEncoder):
    '''
      Handles decimal conversion to json
    '''

    def default(self, o):
        '''
            Extend default from json and replace decimals with
            float or int
        '''

        if isinstance(o, decimal.Decimal):
            if abs(o) % 1 > 0:
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)
