"""
In the root namespaces, the following table shows the various ways to change the three user IDs.
But in non root namespaces, "When a process inside a user namespace executes a set-user-ID
(set-group-ID) program, the process's effective user (group) ID inside the namespace is changed
to whatever value is mapped for the user (group) ID of the file.  However, if either the user
or the group ID of the file has no mapping inside the namespace, the set-user-ID (set-group-ID)
bit is silently ignored: the new program is executed, but the process's effective user (group)
ID is left unchanged"

.-------------------.--------------------------------------------.-----------------------------------.
|                   |                   exec                     |            setuid(uid)            |
|     ID            |---------------------.----------------------.---------------.-------------------.
|                   | set-user-ID bit off | set-user-ID bit On   | superuser     | unprivileged user |
.-------------------.---------------------.----------------------.---------------.-------------------.
| real user ID      | unchanged           | unchanged            | set to uid    | unchanged         |
|                   |                     |                      |               |                   |
.-------------------.---------------------.----------------------.---------------.-------------------.
| effective user ID | unchanged           | set from the user ID | set to uid    | set to uid        |
|                   |                     | of program file      |               |                   |
.-------------------.---------------------.----------------------.---------------.-------------------.
| saved user ID     | copied from the     | copied from the      | set to uid    | unchanged         |
|                   | effective user ID   | effective user ID    |               |                   |
.-------------------.---------------------.----------------------.---------------.-------------------.
"""

import os
import sys
import pwd
import grp
from argparse import ArgumentParser, REMAINDER

from procszoo.c_functions import *
from procszoo.utils import *

def get_options():
    prog = os.path.basename(sys.argv[0]) or 'mamaji'
    project_url = 'http://github.com/procszoo/procszoo'
    description = '%s %s' %('A simple cli to let you run a command',
                                'by some given users and by some give groups')
    parser = ArgumentParser(
        usage='%s [options] [cmd [cmd_options]]' % prog,
        description=description,
        epilog='%s is part of procszoo: %s'  % (prog, project_url))

    parser.add_argument('-v', '--version', action='version',
                            version='%s %s' %  (prog, __version__))
    parser.add_argument(
        '-f', '--fork', action='store_true',
        dest='do_fork', default=True,
        help='fork a subprocess to set user/groups and run cmd in it')
    parser.add_argument(
        '-n', '--no-fork', action='store_false', dest='do_fork')
    parser.add_argument(
        '-u', '--user', action='store', type=str, dest='user',
        metavar='user', help='run cmd as this user')
    parser.add_argument(
        '-g', '--group', action='store', type=str, dest='group',
        metavar='group', help='run cmd as this group')
    parser.add_argument(
        '-G', '--supplementary-group', action='append',
        type=str, dest='groups', metavar='group',
        help='run cmd as this group as a supplementary group')
    parser.add_argument(
        '-l', '--list', action='store_true', dest='show_id',
        help='display current user and groups info')
    parser.add_argument(
        '--real-user', action='store', type=str, dest='real_user',
        metavar='user', help='run cmd as this user as the real user')
    parser.add_argument(
        '--effective-user', action='store', type=str,
        dest='effective_user', metavar='user',
        help='run cmd as this user as the effective user')
    parser.add_argument(
        '--saved-user', action='store', type=str, dest='saved_user',
        metavar='user', help='run cmd as this user as the saved user')
    parser.add_argument(
        '--real-group', action='store', type=str, dest='real_group',
        metavar='group', help='run cmd as this group as the real group')
    parser.add_argument(
         '--effective-group', action='store',
         type=str, dest='effective_group', metavar='group',
         help='run cmd as this group as the effective group')
    parser.add_argument(
        '--saved-group', action='store', type=str, dest='saved_group',
        metavar='group', help='run cmd as this group as the saved group')
    parser.add_argument('cmd', nargs=REMAINDER, action='store', default=None)

    return parser.parse_args()


def fetch_mamaji_data(args):
    ruid, euid, suid = getresuid()
    current_users = {'ruid': ruid, 'euid': euid, 'suid': suid}
    rgid, egid, sgid = getresgid()
    current_groups = {'rgid': rgid, 'egid': egid, 'sgid': sgid}

    pending_users = {'uid': None, 'ruid': None, 'euid': None, 'suid': None}
    if args.user is not None:
        pending_users['uid'] = get_uid_from_name_or_uid(args.user)
    if args.real_user is not None:
        pending_users['ruid'] = get_uid_from_name_or_uid(args.real_user)
    if args.effective_user is not None:
        pending_users['euid'] = get_uid_from_name_or_uid(args.effective_user)
    if args.saved_user is not None:
        pending_users['suid'] = get_uid_from_name_or_uid(args.saved_user)

    pending_groups = {'gid': None, 'rgid': None, 'egid': None, 'sgid': None}
    if args.group is not None:
        pending_groups['gid'] = get_gid_from_name_or_gid(args.group)
    if args.real_group is not None:
        pending_groups['rgid'] = get_gid_from_name_or_gid(args.real_group)
    if args.effective_group is not None:
        pending_groups['egid'] = get_gid_from_name_or_gid(args.effective_group)
    if args.saved_group is not None:
        pending_groups['sgid'] = get_gid_from_name_or_gid(args.saved_group)

    supplementary_groups = []
    if args.groups is not None:
        for group in args.groups:
            supplementary_groups.append(get_gid_from_name_or_gid(group))

    return {'current_users': current_users,
                'current_groups': current_groups,
                'pending_users': pending_users,
                'pending_groups': pending_groups,
                'supplementary_groups': supplementary_groups}


def filter_options(mamaji_data):
    need_super_privilege = False
    action_denied = False

    current_users = mamaji_data['current_users']
    current_groups = mamaji_data['current_groups']
    pending_users = mamaji_data['pending_users']
    pending_groups = mamaji_data['pending_groups']
    supplementary_groups = mamaji_data['supplementary_groups']

    is_super_privilege = (current_users['euid']  == 0)

    if supplementary_groups:
        key = 'supplementary groups'
        need_super_privilege = True
        if not is_super_privilege:
            warn('set "%s" need superuser privileges' % key)

    key = 'euid'
    if pending_users[key] is not None:
        if (pending_users[key] not in
                [current_users['ruid'], current_users['suid']]):
            need_super_privilege = True
            if not is_super_privilege:
                warn('set "%s" need superuser privileges' % key)

    key = 'egid'
    if pending_groups[key] is not None:
        if pending_groups[key] not in [
                current_groups['rgid'], current_groups['sgid']]:
            need_super_privilege = True
            if not is_super_privilege:
                warn('set "%s" need superuser privileges' % key)

    key = 'suid'
    if pending_users[key] is not None:
        need_super_privilege = True
        if not is_super_privilege:
            warn('set "%s" need superuser privileges' % key)
        if pending_users['ruid'] is None or pending_users['euid'] is None:
            action_denied = True
            warn('setting "%s" need set "%s" and "%s", too' %
                       (key, 'ruid', 'euid'))

    key = 'sgid'
    if pending_groups[key] is not None:
        need_super_privilege = True
        if not is_super_privilege:
            warn('set "%s" need superuser privileges' % key)
        if pending_groups['rgid'] is None or pending_groups['egid'] is None:
            action_denied = True
            warn('setting "%s" need set "%s" and "%s", too' %
                       (key, 'rgid', 'egid'))
    key = 'ruid'
    if pending_users[key] is not None:
        need_super_privilege = True
        if not is_super_privilege:
            warn('set "%s" need superuser privileges' % key)
        if pending_users['euid'] is None:
            action_denied = True
            warn('setting "%s" need set "%s" and "%s", too' % (key, 'euid'))

    key = 'rgid'
    if pending_groups[key] is not None:
        need_super_privilege = True
        if not is_super_privilege:
            warn('set "%s" need superuser privileges' % key)
        if pending_groups['egid'] is None:
            action_denied = True
            warn('setting "%s" need set "%s" and "%s", too' %
                       (key, 'egid'))

    if need_super_privilege and not is_super_privilege:
        sys.exit(1)
    if action_denied:
        sys.exit(1)

    return mamaji_data


def show_current_users_and_groups():
    users_and_groups = get_current_users_and_groups()
    head_format_str = '%-21s %-16s %-12s'
    data_format_str = '%-21s %-16s %-12d'

    printf(head_format_str % ('Type', 'Name', 'ID'))
    users = users_and_groups['users']
    for user_type in ['real user', 'effective user', 'saved user']:
        user = users[user_type]
        printf(data_format_str % (user_type, user['name'], user['id']))

    groups = users_and_groups['groups']
    printf('')
    for group_type in ['real group', 'effective group', 'saved group']:
        group = groups[group_type]
        printf(data_format_str % (group_type, group['name'], group['id']))

    supplementary_groups = users_and_groups['supplementary_groups']
    printf('')
    for _group_info in supplementary_groups:
        printf(data_format_str % ('supplementary group',
                _group_info['name'], _group_info['id']))

def change_users_and_groups(mamaji_data):
    current_users = mamaji_data['current_users']
    current_groups = mamaji_data['current_groups']
    pending_users = mamaji_data['pending_users']
    pending_groups = mamaji_data['pending_groups']
    groups = mamaji_data['supplementary_groups']

    if groups:
        os.setgroups(groups)

    group_types = [k for k in ['rgid', 'egid', 'sgid']
                      if pending_groups[k] is not None]
    group_types_len = len(group_types)
    if group_types_len == 3:
        setresgid(pending_groups['rgid'], pending_groups['egid'],
                      pending_groups['sgid'])
    elif group_types_len == 2:
        if 'rgid' in group_types and 'egid' in group_types:
            os.setregid(pending_groups['rgid'], pending_groups['egid'])
    elif group_types_len == 1:
        if 'egid' in group_types:
            os.setegid(pending_groups['egid'])

    user_types = [k for k in ['ruid', 'euid', 'suid']
                      if pending_users[k] is not None]
    user_types_len = len(user_types)
    if user_types_len == 3:
        setresuid(pending_users['ruid'], pending_users['euid'],
                      pending_users['suid'])
    elif user_types_len == 2:
        if 'ruid' in user_types and 'euid' in user_types:
            os.setreuid(pending_users['ruid'], pending_users['euid'])
    elif user_types_len == 1:
        if 'euid' in user_types:
            os.seteuid(pending_users['euid'])


    if pending_groups['gid'] is not None:
        os.setgid(pending_groups['gid'])

    if pending_users['uid'] is not None:
        os.setuid(pending_users['uid'])


def main():
    args = get_options()

    if args.show_id:
        show_current_users_and_groups()
        sys.exit(0)

    mamaji_data = fetch_mamaji_data(args)
    filter_options(mamaji_data)

    target_cmd = None
    if args.cmd:
        target_cmd = args.cmd

    if not args.do_fork:
        change_users_and_groups(mamaji_data)
        # if target_cmd is None, do nothing
        if target_cmd:
            os.execlp(target_cmd[0], *target_cmd)
        sys.exit(0)

    if args.do_fork and not args.cmd:
        target_cmd = [find_shell()]

    pid = os.fork()
    if pid == -1:
        warn('failed to do fork')
        sys.exit(1)
    elif pid == 0:
        change_users_and_groups(mamaji_data)
        os.execlp(target_cmd[0], *target_cmd)
    else:
        status = os.wait4(pid, 0)[1] >> 8
        sys.exit(status)


if __name__ == '__main__':
    main()
