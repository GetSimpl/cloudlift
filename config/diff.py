from terminaltables import SingleTable

from deployment.logging import log_bold


def print_parameter_changes(differences):
    changes_to_show = [["Type", "Config", "Old val", "New val"]]
    for difference in differences:
        if difference[0] == 'change':
            changes_to_show.append([
                'change',
                difference[1],
                difference[2][0],
                difference[2][1]]
            )
        if difference[0] == 'add':
            difference[2].sort(key=lambda x: x[0])
            for added_item in difference[2]:
                changes_to_show.append([
                    'add',
                    added_item[0],
                    '',
                    added_item[1]])
        if difference[0] == 'remove':
            difference[2].sort(key=lambda x: x[0])
            for removed_item in difference[2]:
                changes_to_show.append(['remove', removed_item[0],
                                        removed_item[1], ''])
    log_bold("Modifications to config:")
    print(SingleTable(changes_to_show).table)


def print_json_changes(differences):
    changes_to_show = [["Type", "Config", "Old val", "New val"]]
    for difference in differences:
        if difference[0] == 'change':
            changes_to_show.append([
                'change',
                difference[1],
                difference[2][0],
                difference[2][1]
            ])
        if difference[0] == 'add':
            difference[2].sort(key=lambda x: x[0])
            for added_item in difference[2]:
                changes_to_show.append([
                    'add',
                    difference[1],
                    '',
                    str(added_item[0])+" : "+str(added_item[1])
                ])
        if difference[0] == 'remove':
            difference[2].sort(key=lambda x: x[0])
            for removed_item in difference[2]:
                changes_to_show.append([
                    'remove',
                    str(difference[1])+"."+str(removed_item[0]),
                    removed_item[1],
                    ''
                ])
    log_bold("Modifications to config:")
    print(SingleTable(changes_to_show).table)
