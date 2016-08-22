m4_define(PROCSZOO_VERSION, m4_esyscmd([tr -d '\n' < VERSION]))
AC_INIT(procszoo, PROCSZOO_VERSION, https://github.com/xning/procszoo)

m4_ifdef([AC_COMPUTE_INT], [], [
  AC_DEFUN([AC_COMPUTE_INT], [_AC_COMPUTE_INT([$2],[$1],[$3],[$4])])
])

AC_CHECK_PROG(gcc)

AC_CHECK_HEADERS(syscall.h)

AC_SUBST(NR_PIVOT_ROOT_VAL)
AC_MSG_CHECKING(['__NR_pivot_root' value])
AC_COMPUTE_INT([NR_PIVOT_ROOT_VAL], [__NR_pivot_root], [[#include <syscall.h>]],
  AC_MSG_WARN([syscall.h: could not determine '__NR_pivot_root' value]))
if test "${NR_PIVOT_ROOT_VAL:-}"x != x; then
AC_MSG_RESULT([$NR_PIVOT_ROOT_VAL])
fi

AC_SUBST(NR_SETNS_VAL)
AC_MSG_CHECKING(['__NR_setns' value])
AC_COMPUTE_INT([NR_SETNS_VAL], [__NR_setns], [[#include <syscall.h>]],
  AC_MSG_WARN([syscall.h: could not determine '__NR_setns' value]))
if test "${NR_SETNS_VAL:-}"x != x; then
AC_MSG_RESULT([$NR_SETNS_VAL])
fi

AC_SUBST(ERRNO_EINVAL_VAL)
AC_MSG_CHECKING(['errno EINVAL' value])
AC_COMPUTE_INT([ERRNO_EINVAL_VAL], [EINVAL], [[#include <errno.h>]],
  AC_MSG_WARN([errno.h: could not determine 'EINVAL' value]))
if test "${ERRNO_EINVAL_VAL:-}"x != x; then
AC_MSG_RESULT([$ERRNO_EINVAL_VAL])
fi

AC_SUBST(ERRNO_EPERM_VAL)
AC_MSG_CHECKING(['errno EPERM' value])
AC_COMPUTE_INT([ERRNO_EPERM_VAL], [EPERM], [[#include <errno.h>]],
  AC_MSG_WARN([errno.h: could not determine 'EPERM' value]))
if test "${ERRNO_EPERM_VAL:-}"x != x; then
AC_MSG_RESULT([$ERRNO_EPERM_VAL])
fi

AC_SUBST(PROCSZOO_VERSION_VAL, PROCSZOO_VERSION)
AC_CONFIG_FILES(procszoo/c_functions/macros.py procszoo/version.py)
AC_OUTPUT
