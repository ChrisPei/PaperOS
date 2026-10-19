-- Use upstream rendering/input on KT3; delegate OS policy to PaperOS.
require("setupkoenv")
local app_dir = assert(os.getenv("PAPEROS_APP_DIR"))
local upstream_dofile = dofile
function dofile(path)
    local result = upstream_dofile(path)
    if path == "frontend/ui/elements/common_exit_menu_table.lua" then
        return {exit_menu={text="返回 PaperOS",callback=function()
            require("ui/uimanager"):broadcastEvent(require("ui/event"):new("Exit"))
        end}}
    elseif path == "frontend/ui/elements/reader_menu_order.lua" or path == "frontend/ui/elements/filemanager_menu_order.lua" then
        result.exit_menu = nil
    end
    return result
end
for _, name in ipairs({"reader_menu_order","filemanager_menu_order"}) do
    local path="frontend/ui/elements/"..name..".lua"
    package.preload["ui/elements/"..name]=function()
        local order=assert(loadfile(path))()
        order.exit_menu=nil
        return order
    end
end
local last_activity = 0
local function activity()
    local now = os.time()
    if now ~= last_activity then
        last_activity = now
        os.execute("/usr/sbin/paperos-services ctl lock-activity >/dev/null 2>&1")
    end
end
local function overlay_pending()
    local f = io.open("/run/paperos/state.tsv", "r")
    if not f then return false end
    local active = false
    for line in f:lines() do
        if line:match("^lock\ttrue\t") or line:match("^alert\t") or line:match("^transfer\t") then active = true; break end
    end
    f:close()
    return active
end
package.preload["device"] = function()
    local device = require("device/kindle/device")
    assert(device.model == "KindleBasic2", "This PaperOS adapter targets KT3 only")
    local open_devices = device.openInputDevices
    device.openInputDevices = function(self)
        local open = self.input.open
        self.input.open = function(input, path, ...)
            if path == "fake_events" then return end
            return open(input, path, ...)
        end
        open_devices(self)
    end
    local no = function() return false end
    device.isStartupScriptUpToDate = function() return true end
    device.canSuspend = no
    device.canRestart = no
    device.canReboot = no
    device.canPowerOff = no
    device.hasOTAUpdates = no -- Update the verified .papp, not the read-only runtime.
    device.hasWifiManager = no
    device.hasWifiToggle = no
    device.hasWifiRestore = no
    device.exit = require("device/generic/device").exit
    device.isSpecialOffers = false
    device.setEventHandlers = function() end -- PaperOS owns the power button.
    device.initNetworkManager = function(self, manager)
        manager.isWifiOn = function()
            local f = io.open("/run/paperos/state.tsv", "r")
            if not f then return false end
            local data=f:read("*a");f:close()
            return data:match("\nnet\ttrue\tfalse\t") ~= nil
        end
        manager.isConnected = function()
            local f=io.open("/run/paperos/state.tsv", "r")
            if not f then return false end
            local data=f:read("*a");f:close()
            return data:match("\nnet\ttrue\tfalse\ttrue\t") ~= nil
        end
    end
    local ready = device.UIManagerReady
    device.UIManagerReady = function(self, manager)
        ready(self,manager)
        manager.event_hook:register("InputEvent", activity)
        local function tick()
            if overlay_pending() then
                self.input:teardown()
                self.input:resetState()
                local bridge=app_dir.."/paperos-overlay"
                assert(not bridge:find("'",1,true),"Unexpected app path")
                local status=os.execute("'"..bridge.."' --system-overlay")
                self:openInputDevices()
                self.input:resetState()
                manager:setDirty("all","full")
                if status == 42*256 then
                    manager:broadcastEvent(require("ui/event"):new("Exit"))
                    return
                elseif status ~= 0 then error("PaperOS overlay failed: "..tostring(status)) end
            end
            manager:scheduleIn(0.5,tick)
        end
        manager:scheduleIn(0.1,tick)
    end
    device:init()
    return device
end
dofile("reader.lua")
