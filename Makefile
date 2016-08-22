ifeq ("$(origin V)", "command line")
    Q=
else
    Q=@
endif

PYTHON := /usr/bin/env python

CONFIGURE_OUT := procszoo/c_functions/macros.py procszoo/version.py

all: prepare build_ext

prepare: $(CONFIGURE_OUT)

build_ext:
	$(Q)$(PYTHON) ./setup.py build_ext --inplace

clean:
	$(Q)find . -depth -regex '.*/build\|.*/dist\|.*\.egg-info\|.*/__pycache__' -type d -exec rm -rf '{}' \;
	$(Q)find . -regex '.*\.\(so\|pyc\)\|.*~' -type f -delete
	$(Q)rm -rf configure "$(CONFIGURE_OUT)" autom4te.cache config.log config.status

configure: configure.ac
	$(Q)[ -e configure ] && autoreconf || autoconf

$(CONFIGURE_OUT): configure $(CONFIGURE_OUT:%=%.in)
	$(Q)./configure

.PHONY: all clean build_ext prepare

