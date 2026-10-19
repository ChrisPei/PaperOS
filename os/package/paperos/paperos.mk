PAPEROS_VERSION = 0.1.0
PAPEROS_SITE = $(BR2_EXTERNAL_PAPEROS_PATH)/../native
PAPEROS_SITE_METHOD = local
PAPEROS_LICENSE = GPL-3.0-or-later
PAPEROS_LICENSE_FILES = LICENSE

define PAPEROS_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) \
		CC="$(TARGET_CC)" AR="$(TARGET_AR)" RANLIB="$(TARGET_RANLIB)" \
		ROOT="$(BR2_EXTERNAL_PAPEROS_PATH)/.." \
		OUT="$(@D)/out" KINDLE=1 LDFLAGS="-static" \
		CFLAGS="$(TARGET_CFLAGS) -std=c11 -Wall -Wextra"
endef

define PAPEROS_INSTALL_TARGET_CMDS
	mkdir -p $(TARGET_DIR)/boot/paperos-control $(TARGET_DIR)/old-root
	$(INSTALL) -D -m 0755 $(@D)/out/paperos $(TARGET_DIR)/usr/bin/paperos
	$(INSTALL) -D -m 0755 $(@D)/out/paperos-inputd $(TARGET_DIR)/usr/sbin/paperos-inputd
	$(INSTALL) -D -m 0755 $(@D)/out/paperos-input $(TARGET_DIR)/usr/bin/paperos-input
	$(INSTALL) -D -m 0755 $(BR2_EXTERNAL_PAPEROS_PATH)/../dist/paperos-services $(TARGET_DIR)/usr/sbin/paperos-services
	$(INSTALL) -D -m 0644 $(@D)/input.h $(TARGET_DIR)/usr/include/paperos/input.h
	$(INSTALL) -D -m 0644 $(@D)/out/libpaperos-input.a $(TARGET_DIR)/usr/lib/libpaperos-input.a
	$(INSTALL) -D -m 0644 $(BR2_EXTERNAL_PAPEROS_PATH)/../assets/NotoSansCJKsc-Regular.otf $(TARGET_DIR)/usr/share/paperos/NotoSansCJKsc-Regular.otf
	$(INSTALL) -D -m 0644 $(BR2_EXTERNAL_PAPEROS_PATH)/../assets/Noto-LICENSE.txt $(TARGET_DIR)/usr/share/licenses/paperos/Noto-LICENSE.txt
	$(foreach app,alarm calendar weather mihome,$(INSTALL) -D -m 0644 $(BR2_EXTERNAL_PAPEROS_PATH)/../examples/$(app).papp/manifest.conf $(TARGET_DIR)/var/lib/paperos/apps/org.paperos.$(app)/manifest.conf;)
	$(foreach app,alarm calendar weather mihome,$(INSTALL) -D -m 0755 $(BR2_EXTERNAL_PAPEROS_PATH)/../examples/$(app).papp/run.sh $(TARGET_DIR)/var/lib/paperos/apps/org.paperos.$(app)/run.sh;)
	$(INSTALL) -D -m 0644 $(BR2_EXTERNAL_PAPEROS_PATH)/../examples/notes.papp/manifest.conf $(TARGET_DIR)/var/lib/paperos/apps/org.paperos.notes/manifest.conf
	$(INSTALL) -D -m 0755 $(BR2_EXTERNAL_PAPEROS_PATH)/../examples/notes.papp/run.sh $(TARGET_DIR)/var/lib/paperos/apps/org.paperos.notes/run.sh
endef

$(eval $(generic-package))
