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
	$(Q)rm -rf configure $(CONFIGURE_OUT) autom4te.cache config.log config.status
	$(Q)rm -rf .pybuild debian/debhelper-build-stamp debian/files
	$(Q)rm -rf debian/*.log debian/*.debhelper debian/*.substvars
	$(Q)rm -rf debian/python-procszoo debian/python3-procszoo .pybuild
	$(Q)rm -rf procszoo/network/dhcp.py

configure: configure.ac
	$(Q)[ -e configure ] && autoreconf || autoconf

$(CONFIGURE_OUT): configure $(CONFIGURE_OUT:%=%.in)
	$(Q)./configure

# Packaging
VERSION := $(shell tr -d '\n' < VERSION)

dist:
	$(Q)$(PYTHON) ./setup.py sdist

RPMBUILD_TOPDIR := build/rpmbuild
RPM_OUTDIR := dist
SRPM_OUTDIR := dist

srpm: dist
	$(Q)cp VERSION dist/VERSION
	$(Q)mkdir -p "$(RPMBUILD_TOPDIR)" "$(SRPM_OUTDIR)"
	$(Q)rpmbuild --define "_topdir $(shell pwd)/$(RPMBUILD_TOPDIR)" --clean -ts "dist/procszoo-$(VERSION).tar.gz"
	$(Q)cp -a "$(RPMBUILD_TOPDIR)"/SRPMS/*.rpm "$(SRPM_OUTDIR)"

rpm: dist
	$(Q)cp VERSION dist/VERSION
	$(Q)mkdir -p "$(RPMBUILD_TOPDIR)" "$(RPM_OUTDIR)" "$(SRPM_OUTDIR)"
	$(Q)rpmbuild --define "_topdir $(shell pwd)/$(RPMBUILD_TOPDIR)" --clean -ta "dist/procszoo-$(VERSION).tar.gz"
	$(Q)cp -a "$(RPMBUILD_TOPDIR)"/{SRPMS,RPMS/*}/*.rpm "$(SRPM_OUTDIR)"

deb:
	$(Q)debuild -us -uc

.PHONY: all clean build_ext prepare dist srpm rpm deb
