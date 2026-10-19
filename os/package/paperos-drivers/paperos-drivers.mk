PAPEROS_DRIVERS_VERSION = 5.16.2.1.1
PAPEROS_DRIVERS_SITE = $(BR2_EXTERNAL_PAPEROS_PATH)/../build/kt3-drivers
PAPEROS_DRIVERS_SITE_METHOD = local
PAPEROS_DRIVERS_LICENSE = GPL-2.0, proprietary (EPDC companion)

define PAPEROS_DRIVERS_INSTALL_TARGET_CMDS
	cp -a $(@D)/lib/. $(TARGET_DIR)/lib/
	cp -a $(@D)/opt $(TARGET_DIR)/
	$(HOST_DIR)/sbin/depmod -b $(TARGET_DIR) 3.10.53-lab126
	$(INSTALL) -D -m 0644 $(@D)/sources.json $(TARGET_DIR)/usr/share/paperos/driver-sources.json
endef

$(eval $(generic-package))
