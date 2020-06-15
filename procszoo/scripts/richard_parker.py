import os
import sys
from argparse import ArgumentParser, REMAINDER
import traceback
from procszoo.c_functions import *
from procszoo.utils import *


def get_options():
    propagation_types = get_available_propagations()
    available_namespaces = [
        ns_status[0] for ns_status in show_namespaces_status()
                                 if ns_status[1]]
    prog = os.path.basename(sys.argv[0]) or 'richard_parker'
    project_url = "http://github.com/procszoo/procszoo"
    description = "%s, %s" % (
        'A simple cli to create new namespaces env',
        'default it will enable each available namespaces.')
    parser = ArgumentParser(
        usage="%s [options] [nscmd] [nscmd_options]" % prog,
        description=description,
        epilog="%s is part of procszoo: %s"  % (prog, project_url))

    parser.add_argument('-v', '--version', action='version',
                            version='%s %s' %  (prog, __version__))
    parser.add_argument("-n", "--namespace", action="append",
                            dest="namespaces", choices=available_namespaces,
                            help="namespace that should be create")
    parser.add_argument("-N", "--negative-namespace", action="append",
                          dest="negative_namespaces",
                          choices=available_namespaces,
                          help="namespace that should not be create")
    parser.add_argument("-i", "--interactive", action="store_true",
                            dest="interactive", default=True,
                            help="enable interactive mode")
    parser.add_argument('-B', '--batch', action="store_false",
                            dest="interactive",
                            help='enable batch mode')
    help_str = "map current effective user/group to root/root, implies -n user"
    parser.add_argument("-r", "--maproot", action="store_true", dest="maproot",
                            default=True, help=help_str)
    parser.add_argument("--no-maproot", action="store_false", dest="maproot")
    parser.add_argument("-u", "--user-map", action="append", dest="users_map",
                            metavar='name_or_uid',
                            type=str,
                            help="user map settings, implies -n user")
    parser.add_argument("-g", "--group-map", action="append",
                            dest="groups_map", type=str, metavar='name_or_gid',
                            help="group map settings, implies -n user")
    parser.add_argument("--init-program", action="store", dest="init_prog",
                            type=str, metavar='your_init_program',
                            help="replace the my_init program by yours")
    help_str = """
    control the setgroups syscall in user namespaces,
    when setting to 'allow' will enable --no-maproot option and avoid
    --user-map and --group-map options
    """
    parser.add_argument(
        "-s", "--setgroups", action="store", type=str, dest="setgroups",
        choices=['allow', 'deny'],
        help=help_str)
    parser.add_argument("--mountproc", action="store_true", dest="mountproc",
                        help="remount procfs mountpoin, implies -n mount",
                      default=True)
    parser.add_argument("--no-mountproc", action="store_false",
                            dest="mountproc",
                            help="do not remount procfs")
    parser.add_argument("--mountpoint", action="store", type=str,
                        dest="mountpoint",
                        help="dir that the new procfs would be mounted to")
    parser.add_argument("-b", "--ns-bind-dir", action="store", type=str,
                        dest="ns_bind_dir", metavar='dir',
                        help="dir that the new namespaces would be mounted to")
    parser.add_argument(
        "--propagation", action="store", type=str, dest="propagation",
        choices=propagation_types,
        help="modify mount propagation in mount namespace")
    parser.add_argument("-l", "--list", action="store_true",
                          dest="show_ns_status", default=False,
                          help="list namespaces status")
    parser.add_argument("--dhcp", action="store_true", dest="dhcp",
                            default=True, help='to dhcp network interface')
    parser.add_argument("--no-dhcp", action="store_false", dest="dhcp",
                            help='not to dhcp network interface')
    parser.add_argument(
        "--hostname", action="store", type=str, dest="hostname",
        metavar='hostname',
        help="hostname in the new net namespaces")
    help_str = '''
    if network is macvtap, will create macvtap on this interface;
    if network is veth, will add the interface as physical device
    to the bridge
    '''
    parser.add_argument(
        "--interface", action="store", type=str, dest="interface",
        metavar='interface',
        help=help_str)
    parser.add_argument(
        "--nameserver", action="append", type=str, dest="nameservers",
        metavar='nameserver', help="nameserver in the new net namespaces")
    parser.add_argument(
        "--network", action="store", nargs='?', type=str, dest="network",
        choices=['macvtap', 'veth'], const='macvtap',
        help="network type")
    parser.add_argument(
        "--bridge", action="store", type=str, dest="bridge", metavar='bridge',
        help='bridge in parent namespaces')
    parser.add_argument("--available-c-functions", action="store_true",
                        dest="show_available_c_functions",
                        help="show available C functions",
                        default=False)
    parser.add_argument('nscmd', nargs=REMAINDER, action="store", default=None)

    return parser.parse_args()

def show_namespaces_then_quit():
    for v in show_namespaces_status():
        printf("%-6s: %-5s" % v)
    sys.exit(0)


def show_available_c_functions_and_quit():
    printf("%s" % "\n".join(workbench.show_available_c_functions()))
    sys.exit(0)


def main():
    check_namespaces_available_status()
    args = get_options()

    if args.show_ns_status:
        show_namespaces_then_quit()
    if args.show_available_c_functions:
        show_available_c_functions_and_quit()

    if args.network or args.nameservers or args.hostname:
        try:
            from procszoo.network import cli
        except (SystemExit, KeyboardInterrupt) as e:
            printf(e)
            sys.exit(1)
        extra = cli.build_extra(args)
    else:
        extra = None

    _exit_code = 0
    try:
        spawn_namespaces(
            namespaces=args.namespaces,
            negative_namespaces=args.negative_namespaces,
            maproot=args.maproot,
            mountproc=args.mountproc,
            mountpoint=args.mountpoint,
            ns_bind_dir=args.ns_bind_dir,
            propagation=args.propagation,
            nscmd=args.nscmd, users_map=args.users_map,
            groups_map=args.groups_map,
            setgroups=args.setgroups,
            init_prog=args.init_prog,
            interactive=args.interactive,
            extra=extra)

    except UnavailableNamespaceFound as e:
        printf(e)
        _exit_code = 1
    except NamespaceRequireSuperuserPrivilege as e:
        printf(e)
        _exit_code = 1
    except NamespaceSettingError as e:
        printf(e)
        _exit_code = 1
    except RuntimeError as e:
        printf(e)
        _exit_code = 1
    except KeyboardInterrupt:
        _exit_code = 1
    except Exception as e:
        printf(e)
        traceback.print_exc()
        _exit_code = 1
    sys.exit(_exit_code)


if __name__ == "__main__":
    main()
