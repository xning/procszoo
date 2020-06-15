__all__ = [
    'Pyroute2ModuleUnvailable', 'Pyroute2NetNSUnvailable',
    'NetworkSettingError', 'InterfaceNotFound',
    'UnkonwnInterfaceFound', 'DHCPFailed',
    ]


class Pyroute2ModuleUnvailable(Exception):
    pass


class Pyroute2NetNSUnvailable(Pyroute2ModuleUnvailable):
    pass


class NetworkSettingError(Exception):
    pass

class InterfaceNotFound(NetworkSettingError):
    pass

class UnkonwnInterfaceFound(NetworkSettingError):
    pass

class DHCPFailed(NetworkSettingError):
    pass
