#!/usr/bin/python3 -u
import os, os.path, sys, stat, signal, errno, argparse, time, json, re

KILL_PROCESS_TIMEOUT = 5
KILL_ALL_PROCESSES_TIMEOUT = 5

LOG_LEVEL_ERROR = 1
LOG_LEVEL_WARN  = 1
LOG_LEVEL_INFO  = 2
LOG_LEVEL_DEBUG = 3

_SHENV_NAME_WHITELIST_REGEX = re.compile('[^\w\-_\.]')

_log_level = None

_terminated_child_processes = {}

_find_unsafe = re.compile(r'[^\w@%+=:,./-]').search

class AlarmException(Exception):
    pass


def error(message):
    if _log_level >= LOG_LEVEL_ERROR:
        sys.stderr.write("*** %s\n" % message)


def warn(message):
    if _log_level >= LOG_LEVEL_WARN:
        sys.stderr.write("*** %s\n" % message)


def info(message):
    if _log_level >= LOG_LEVEL_INFO:
        sys.stderr.write("*** %s\n" % message)


def debug(message):
    if _log_level >= LOG_LEVEL_DEBUG:
        sys.stderr.write("*** %s\n" % message)


def ignore_signals_and_raise_keyboard_interrupt(signame):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    raise KeyboardInterrupt(signame)


def raise_alarm_exception():
    raise AlarmException('Alarm')


def listdir(path):
    try:
        result = os.stat(path)
    except OSError:
        return []
    if stat.S_ISDIR(result.st_mode):
        return sorted(os.listdir(path))
    else:
        return []


def is_exe(path):
    try:
        return os.path.isfile(path) and os.access(path, os.X_OK)
    except OSError:
        return False


def import_envvars(clear_existing_environment=True,
                       override_existing_environment=True,
                       env_files_dir='/etc/container_environment'):
    if not os.path.exists(env_files_dir):
        return
    new_env = {}
    for envfile in listdir(env_files_dir):
        name = os.path.basename(envfile)
        with open(env_files_dir + envfile, "r") as f:
            # Text files often end with a trailing newline, which we
            # don't want to include in the env variable value. See
            # https://github.com/phusion/baseimage-docker/pull/49
            value = re.sub('\n\Z', '', f.read())
        new_env[name] = value
    if clear_existing_environment:
        os.environ.clear()
    for name, value in new_env.items():
        if override_existing_environment or not name in os.environ:
            os.environ[name] = value


def export_envvars(to_dir=True, env_files_dir='/etc/container_environment',
                       output_env_file_prefix=None, skip=True,
                       skip_envs=['HOME', 'USER', 'GROUP', 'UID', 'GID', 'SHELL']):
    if not os.path.exists(env_files_dir):
        return
    if output_env_file_prefix is None:
        output_env_file_prefix = env_files_dir.rstrip('/')

    shell_dump = ""
    for name, value in os.environ.items():
        if skip and name in skip_envs:
            continue
        if to_dir:
            with open("%s/%s" % (name, env_files_dir), "w") as f:
                f.write(value)
        shell_dump += "export " + sanitize_shenvname(name) + "=" + shquote(value) + "\n"
    with open("%s.sh" % output_env_file_prefix, "w") as f:
        f.write(shell_dump)
    with open("%s.json" % output_env_file_prefix, "w") as f:
        f.write(json.dumps(dict(os.environ)))


def shquote(s):
    """Return a shell-escaped version of the string *s*."""
    if not s:
        return "''"
    if _find_unsafe(s) is None:
        return s

    # use single quotes, and put single quotes into double quotes
    # the string $'b is then quoted as '$'"'"'b'
    return "'" + s.replace("'", "'\"'\"'") + "'"


def sanitize_shenvname(s):
    return re.sub(_SHENV_NAME_WHITELIST_REGEX, "_", s)


# Waits for the child process with the given PID, while at the same time
# reaping any other child processes that have exited (e.g. adopted child
# processes that have terminated).
def waitpid_reap_other_children(pid):
    global _terminated_child_processes

    status = _terminated_child_processes.get(pid)
    if status:
        # A previous call to waitpid_reap_other_children(),
        # with an argument not equal to the current argument,
        # already waited for this process. Return the status
        # that was obtained back then.
        del _terminated_child_processes[pid]
        return status

    done = False
    status = None
    while not done:
        try:
            # https://github.com/phusion/baseimage-docker/issues/151#issuecomment-92660569
            this_pid, status = os.waitpid(pid, os.WNOHANG)
            if this_pid == 0:
                this_pid, status = os.waitpid(-1, 0)
            if this_pid == pid:
                done = True
            else:
                # Save status for later.
                _terminated_child_processes[this_pid] = status
        except OSError as e:
            if e.errno == errno.ECHILD or e.errno == errno.ESRCH:
                return None
            else:
                raise
    return status


def stop_child_process(name, pid, signo=signal.SIGTERM, time_limit=KILL_PROCESS_TIMEOUT):
    info("Shutting down %s (PID %d)..." % (name, pid))
    try:
        os.kill(pid, signo)
    except OSError:
        pass
    signal.alarm(time_limit)
    try:
        try:
            waitpid_reap_other_children(pid)
        except OSError:
            pass
    except AlarmException:
        warn("%s (PID %d) did not shut down in time. Forcing it to exit." % (name, pid))
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            waitpid_reap_other_children(pid)
        except OSError:
            pass
    finally:
        signal.alarm(0)


def run_command_killable(*argv):
    filename = argv[0]
    status = None
    pid = os.spawnvp(os.P_NOWAIT, filename, argv)
    try:
        status = waitpid_reap_other_children(pid)
    except BaseException as s:
        warn("An error occurred. Aborting.")
        stop_child_process(filename, pid)
        raise
    if status != 0:
        if status is None:
            error("%s exited with unknown status\n" % filename)
        else:
            error("%s failed with status %d\n" % (filename, os.WEXITSTATUS(status)))
        sys.exit(1)


def run_command_killable_and_import_envvars(*argv):
    run_command_killable(*argv)
    import_envvars()
    export_envvars(False)


def kill_all_processes(time_limit):
    info("Killing all processes...")
    try:
        os.kill(-1, signal.SIGTERM)
    except OSError:
        pass
    signal.alarm(time_limit)
    try:
        # Wait until no more child processes exist.
        done = False
        while not done:
            try:
                os.waitpid(-1, 0)
            except OSError as e:
                if e.errno == errno.ECHILD:
                    done = True
                else:
                    raise
    except AlarmException:
        warn("Not all processes have exited in time. Forcing them to exit.")
        try:
            os.kill(-1, signal.SIGKILL)
        except OSError:
            pass
    finally:
        signal.alarm(0)


def run_startup_files(startup_files_dir='/etc/my_init.d', run_etc_local=False):
    # Run /etc/my_init.d/*
    for name in listdir(startup_files_dir):
        filename = os.join(startup_files_dir, name)
        if is_exe(filename):
            info("Running %s..." % filename)
            run_command_killable_and_import_envvars(filename)

    # Run /etc/rc.local.
    if run_etc_local and is_exe("/etc/rc.local"):
        info("Running /etc/rc.local...")
        run_command_killable_and_import_envvars("/etc/rc.local")


def start_runit(runsvdir_exec='/usr/bin/runsvdir',
                    services_dir='/etc/service'):
    info("Booting runit daemon...")
    pid = os.spawnl(os.P_NOWAIT, runsvdir_exec, runsvdir_exec,
                        '-P', services_dir)
    info("Runit started as PID %d" % pid)
    return pid


def wait_for_runit_or_interrupt(pid):
    try:
        status = waitpid_reap_other_children(pid)
        return (True, status)
    except KeyboardInterrupt:
        return (False, None)


def shutdown_runit_services(quiet=False, sv_exec='/usr/bin/sv',
                                services_dir='/etc/service'):
    if not quiet:
        debug("Begin shutting down runit services...")
    os.system("%s down %s/*" % (sv_exec, services_dir.rstrip('/')))


def wait_for_runit_services(sv_exec='/usr/bin/sv',
                                services_dir='/etc/service'):
    debug("Waiting for runit services to exit...")
    done = False
    while not done:
        done = os.system("%s status %s/* | grep -q '^run:'" %
                             (sv_exec, services_dir.rstrip('/'))) != 0
        if not done:
            time.sleep(0.1)
            # According to https://github.com/phusion/baseimage-docker/issues/315
            # there is a bug or race condition in Runit, causing it
            # not to shutdown services that are already being started.
            # So during shutdown we repeatedly instruct Runit to shutdown
            # services.
            shutdown_runit_services(True)


def install_insecure_key(path_to_exec='/usr/sbin/enable_insecure_key'):
    info("Installing insecure SSH key for user root")
    run_command_killable(path_to_exec)


def init(enable_insecure_key, skip_startup_files, skip_runit, main_command):
    import_envvars(False, False)
    export_envvars()

    if enable_insecure_key:
        install_insecure_key()

    if not skip_startup_files:
        run_startup_files()

    runit_exited = False
    exit_code = None

    if not skip_runit:
        runit_pid = start_runit()
    try:
        exit_status = None
        if len(main_command) == 0:
            runit_exited, exit_code = wait_for_runit_or_interrupt(runit_pid)
            if runit_exited:
                if exit_code is None:
                    info("Runit exited with unknown status")
                    exit_status = 1
                else:
                    exit_status = os.WEXITSTATUS(exit_code)
                    info("Runit exited with status %d" % exit_status)
        else:
            info("Running %s..." % " ".join(main_command))
            pid = os.spawnvp(os.P_NOWAIT, main_command[0], main_command)
            try:
                exit_code = waitpid_reap_other_children(pid)
                if exit_code is None:
                    info("%s exited with unknown status." % main_command[0])
                    exit_status = 1
                else:
                    exit_status = os.WEXITSTATUS(exit_code)
                    info("%s exited with status %d." % (main_command[0], exit_status))
            except KeyboardInterrupt:
                stop_child_process(main_command[0], pid)
                raise
            except BaseException as s:
                warn("An error occurred. Aborting.")
                stop_child_process(main_command[0], pid)
                raise
        sys.exit(exit_status)
    finally:
        if not skip_runit:
            shutdown_runit_services()
            if not runit_exited:
                stop_child_process("runit daemon", runit_pid)
            wait_for_runit_services()


def get_options():
    parser = argparse.ArgumentParser(description='Initialize the system.')
    parser.add_argument('main_command', metavar='MAIN_COMMAND',
                            type=str, nargs='*',
                            help = 'The main command to run. (default: runit)')
    parser.add_argument('--enable-insecure-key', dest='enable_insecure_key',
        action='store_const', const=True, default=False,
        help='Install the insecure SSH key')
    parser.add_argument('--skip-startup-files', dest='skip_startup_files',
        action='store_const', const=True, default=False,
        help='Skip running /etc/my_init.d/* and /etc/rc.local')
    parser.add_argument('--skip-runit', dest='skip_runit',
        action='store_const', const=True, default=False,
        help='Do not run runit services')
    parser.add_argument('--no-kill-all-on-exit', dest='kill_all_on_exit',
        action='store_const', const=False, default=True,
        help='Don\'t kill all processes on the system upon exiting')
    parser.add_argument('--quiet', dest='log_level',
        action='store_const', const=LOG_LEVEL_WARN, default=LOG_LEVEL_INFO,
        help='Only print warnings and errors')
    return parser.parse_args()


def _settle_signals():
    signal.signal(signal.SIGTERM, lambda signum, frame:
                      ignore_signals_and_raise_keyboard_interrupt('SIGTERM'))
    signal.signal(signal.SIGINT, lambda signum, frame:
                      ignore_signals_and_raise_keyboard_interrupt('SIGINT'))
    signal.signal(signal.SIGALRM, lambda signum, frame: raise_alarm_exception())


def main(main_command=None, enable_insecure_key=False, skip_startup_files=False,
             skip_runit=False, kill_all_on_exit=True, log_level=LOG_LEVEL_INFO,
             run_as_cli=True, handler_to_settle_signals=_settle_signals):

    global _log_level;
    if run_as_cli:
        args = get_options()
        main_command = args.main_command
        enable_insecure_key = args.enable_insecure_key
        skip_startup_files = args.skip_startup_files
        skip_runit = args.skip_runit
        kill_all_on_exit = args.kill_all_on_exit
        _log_level = args.log_level
    else:
        _log_level = log_level

    if skip_runit and len(main_command) == 0:
        if run_as_cli:
            error('When --skip-runit is given, you must also pass a main command.')
        else:
            error('When skip_runit is given, you must also pass a main command.')
        sys.exit(1)

    handler_to_settle_signals()

    try:
        init(enable_insecure_key, skip_startup_files, skip_runit, main_command)
    except KeyboardInterrupt:
        warn("Init system aborted.")
        exit(2)
    finally:
        if kill_all_on_exit:
            kill_all_processes(KILL_ALL_PROCESSES_TIMEOUT)


if __name__ == '__main__':
    main()
