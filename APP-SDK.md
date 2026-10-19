# PaperOS 应用包

PaperOS 是常驻的原生启动器。首页承载应用提供的 Widget，底部“应用”列出已安装应用和接收的应用包，支持安装、更新、打开和卸载。闹钟、万年历、天气、米家和记事本是独立应用；记事本不占主页。卸载应用会移除对应组件，应用数据保留。

打开应用时，启动器释放触控设备并停止绘图；应用退出或崩溃后，启动器重新接管触控和屏幕，恢复原来的页面。切换应用不需要重启 Kindle。独立系统的 init 会在开机时启动 PaperOS；真机已经验证重启自动进入，启动器常驻运行。

当前启动器、应用管理和界面使用 C，后台计时、网络、天气和接收服务使用 Go，应用包通过 Shell 脚本指定入口；电脑端发送、构建辅助和验证工具主要使用 Python。提供的原生应用启动同一个 `/usr/bin/paperos` 可执行文件的不同模式，各自运行在独立进程中。卸载它们会删除包目录与组件入口，共享可执行文件中的对应功能代码仍然保留。应用包也可以携带独立编译的 ARM 可执行文件，启动器执行清单指定的入口；卸载时该包中的程序随目录一起删除。

这些进程目前使用 root 身份，一次运行一个前台应用；独立进程不代表已有应用权限沙箱。

## 安装和管理

应用包是一个以 `.papp` 结尾的目录。无线发送支持可互通的局域网地址，以及同一 Tailscale 私网内获准访问的设备地址。在 Kindle“设置”中开启“接收应用”，再运行：

```powershell
python scripts/push-app.py examples/alarm.papp --host <Kindle的Wi-Fi地址>
# 跨 Wi-Fi：填“设置 → Tailscale”显示的 100.x.x.x 地址
python scripts/push-app.py examples/alarm.papp --host <Kindle的Tailscale地址>
```

电脑和 Kindle 显示相同的六位校验码；在 Kindle 核对后点“确认接收”。通过验证的包放入 `/mnt/us/paperos/packages/`，再在“应用 → 接收的应用包”选择安装或更新。安装完成后，在“已安装”列表打开。卸载需要点“确认卸载”，应用数据保留。

设备自动生成 TLS 证书；校验码绑定证书、包摘要和本次随机数。局域网和 Tailscale 使用同一证书、相同确认流程，远程请求在屏幕标为“Tailscale 私网”。确认成功后，电脑保存证书摘要和默认 IP，后续把整个 `.papp` 目录拖到 `send-app.cmd` 即可默认无线发送；每次仍需设备端确认。使用 Tailscale 地址配对后，默认发送地址不随 Wi-Fi 的局域网 IP 改变。接收窗口为 10 分钟，开启飞行模式或关闭无线会关闭接收服务；休眠或未联网时须先唤醒并联网。证书变化时发送工具会拒绝连接，需要核对设备后重新配对。此流程只接收包，不自动安装或执行包内代码。

“设置 → Tailscale”显示连接状态、设备名称、私网 IPv4 地址和客户端版本，提供持久的“私网连接”“允许远程接收应用”开关及状态刷新。远程接收还要求主设置页的十分钟“接收应用”窗口已开启；关闭远程接收只关闭私网入口，并拒绝尚未确认的远程包，局域网入口可继续使用。关闭整个私网连接会暂停远程米家读数，已缓存指标保留；重新开启沿用原有设备身份。此页面不更换账户、重置设备身份或修改网络访问策略。

后端分别在 Wi-Fi 的具体地址和 `127.0.0.1:8765` 监听 TLS。Tailscale userspace networking 将获准的私网入站 TCP 转交环回入口，不使用通配地址、Serve、Funnel 或路由器端口映射。仅新增电脑到 Kindle 的接收通道，不修改 Kindle 到 NAS 的访问权限；NAS 仍仅开放选中指标的只读网关。发送工具支持私网 IPv4 和 Tailscale 的 `100.64.0.0/10` 地址。

`/run/paperos/state.tsv` 的 `tailnet` 行依次为：客户端已安装、私网连接已启用、允许远程接收、当前已连接、状态更新中、设备名称、私网 IPv4、客户端版本、消息、私网接收入口已就绪。包含行名共 11 列，布尔值为 `true` / `false`，空字符串为 `-`。控制仍走本机 Unix socket：`tailnet-enable enabled true|false`、`tailnet-receive enabled true|false`、`tailnet-refresh`。这些接口不通过应用接收端口公开。

USB 发送仍可用：保持连接，运行 `python scripts/push-app.py examples/alarm.papp --usb`。没有无线配对记录时，不指定 `--host` 的发送也默认使用 USB。

USB 使用网络传输；不把正在承载根文件系统的存储同时作为 Windows 磁盘导出。应用包目录仍通过 `/mnt/us/paperos/packages/` 访问。

同一个 `id` 再次安装会更新应用。程序先完整复制、校验到暂存目录，再替换旧应用；常规安装失败会保留原版本。正在运行的应用会阻止其他安装、更新或卸载操作。首版每包最多 256 个目录项、64 MiB，目录嵌套最多 8 层；包内不接受符号链接、设备文件或其他特殊文件。

应用需要适配 ARMv7、32 位 soft-float 和 Linux 3.10.53。可使用静态编译的原生程序，或者带 LF 换行和 `#!/bin/sh` 的脚本；其他发行版的动态程序还需自己的匹配运行库。

## 文件格式

```text
clock.papp/
  manifest.conf
  run.sh
```

`manifest.conf` 是 UTF-8 文本，不执行其中的代码：

```ini
id=org.paperos.clock
name=独立时钟
version=0.1.0
exec=run.sh
description=应用退出后返回启动器的示例
```

`id` 仅使用小写英文字母、数字、点、横线和下划线，不能以点开头，不能包含连续的两个点。`exec` 是包内的相对路径，可以是 `bin/my-app`；不能使用绝对路径或 `..`。必填字段是 `id`、`name`、`version` 和 `exec`；可选字段为 `description`、`widget`，不允许重复或未知字段。

应用安装在 `/var/lib/paperos/apps/<id>/`。应用的数据与程序分开存放；不要把用户数据写进应用安装目录。

`examples/ace-attorney-1.papp/` 展示携带独立 ARM 可执行程序的游戏包，构建产物在 `dist/ace-attorney-1.papp/`。该程序复用 PaperOS 原生锁屏和提醒绘制代码，游戏文件与存档均放在包目录以外，卸载不删除进度。休眠程序会一并暂停由 `/usr/bin/paperos` 直接启动、程序位于安装目录内的原生前台进程，按 PID 和启动时刻确认身份后恢复；这不替代应用在休眠前完成屏幕清理与确认的责任。接电不休眠的规则继续适用。接入细节见 [native/nds/README.md](native/nds/README.md)。

## 主页 Widget

支持组件的应用在清单中声明模板，例如闹钟应用：

```ini
id=org.paperos.alarm
name=闹钟
version=0.2.0
exec=run.sh
description=时钟、闹钟、倒计时与黑白提醒
widget=clock
```

当前提供四种固定模板：`clock`、`calendar`、`weather`、`mihome`。主页根据已安装清单寻找提供者，点击组件会启动该应用；组件并非单独运行的网页或进程。增加任意新组件样式仍需扩展原生渲染器，当前不能仅通过清单上传任意绘图代码。

“设置 → 首页组件”管理显示和顺序，配置保存在应用根目录 `/.widgets.conf`。隐藏组件不卸载应用；卸载应用后其组件不可用。卸载 `org.paperos.alarm` 还会禁用闹钟并清除倒计时、延后提醒和当前提醒，原有闹钟数据保留。

## 应用运行接口

启动器提供以下环境变量：

| 变量 | 含义 |
|---|---|
| `PAPEROS_APP_ID` | 当前应用的编号 |
| `PAPEROS_APP_DIR` | 当前应用的安装目录，也是启动时的工作目录 |
| `PAPEROS_DATA_DIR` | 当前应用自己的数据目录，更新和卸载均保留 |
| `PAPEROS_LAUNCHER` | 原生 PaperOS 程序的绝对路径 |
| `PAPEROS_FONT` | 当前中文字体文件路径 |

应用要提供返回按钮，点击后正常退出自己的进程。启动器会等待进程结束再恢复屏幕；它也会在收到停止信号时终止该应用的进程组。首版一次运行一个前台应用。

`examples/clock.papp/run.sh` 展示如何复用原生界面的独立应用模式：

```sh
#!/bin/sh
exec "$PAPEROS_LAUNCHER" --standalone --screen clock
```

独立应用模式显示“返回主页”按钮。这个示例由独立进程运行，已验证安装、打开、退出和屏幕/触控交接。自己的程序可以直接使用 framebuffer 和 evdev；启动器不会继续占用触控设备。`clock.papp` 保留为旧版 SDK 示例，新系统默认安装 `alarm.papp`，使用 `--screen alarm`。

`examples/notes.papp/run.sh` 用 `--standalone --screen notes --note "$PAPEROS_DATA_DIR/note.txt"` 打开独立记事本。笔记保存在这个应用自己的数据目录；点击“保存”后写入磁盘。卸载和重新安装应用均保留已保存的笔记。

也可通过调试 shell 管理应用：

```sh
paperos --install /mnt/us/paperos/packages/clock.papp
paperos --list-apps
paperos --run-app org.paperos.clock
paperos --remove org.paperos.clock
```

调试时可用 `--app-root DIR` 和 `--packages DIR` 指定测试目录。

## 后台服务与全屏提醒

`paperos-services` 独立管理闹钟、倒计时、网络、自动对时、天气和休眠，保存状态到 `/var/lib/paperos/services/state.json`；监视进程在服务异常退出后自动恢复。相对计时使用内核启动标识和包含休眠时间的 `/proc/uptime`，修改系统时钟不会改变同一次启动内的剩余时长。正常重启后按保存的截止时间恢复。KT3 真机使用 RTC 在最近提醒前唤醒；模拟环境不会执行硬件休眠。

自动对时在联网后及每 6 小时运行一次，失败后退避 5 分钟；后台网络请求不会阻塞触控。命令 `time-sync` 请求立即同步，`time-auto enabled true|false` 修改保存的自动对时开关；`time-set value "2026-10-16 12:00"` 仅在自动对时关闭时接受手动时间。状态快照的 `clock` 行包含自动开关、同步中标志、上次成功同步的 Unix 时间、来源和结果消息。`--probe-time` 只读取网络时间，不修改时钟，可用于连接诊断；`--simulate` 环境拒绝实际校时。

本机状态快照为 `/run/paperos/state.tsv`，命令通过受本机文件权限保护的 Unix socket `/run/paperos/services.sock` 发送。C 接口见 [native/services.h](native/services.h)：`paperos_services_read()` 读取状态，`paperos_service_command()` 发送命令及以 NULL 结尾的键值参数。Shell 示例：

```sh
paperos-services ctl timer-start seconds 1500
paperos-services ctl timer-pause
paperos-services ctl timer-resume
paperos-services ctl timer-cancel
```

提供的 PaperOS 原生应用和公共键盘都检查后台状态，在提醒到期时保存当前界面状态并显示全屏提示，每 2 秒黑白切换。“停止”恢复原界面，“稍后提醒”延后 5 分钟。接收应用的确认页使用同一套覆盖机制。

自行直接接管 framebuffer/evdev 的应用需要接入状态轮询、提醒绘制和触控处理，或复用现有原生应用模式。当前没有对任意第三方进程强制夺取屏幕和触控的通用机制，不能假定未接入的应用也支持全局提醒。

## 天气地区

天气地区保存在服务配置 `WeatherLocation` 中，包括 `Name`、`Area`、`Latitude`、`Longitude`；旧配置自动沿用北京朝阳预设及其缓存。主状态的 `weather-location` 行依次为名称、所属地区、纬度、经度、是否正在更新。应用与主页均从这一行读取名称，预报仍使用原有 `weather` / `hour` 行，按设备北京时间显示。

`weather-search query <地名>` 异步搜索国内地区，要求联网。`location-search` 行依次为查询词、下载中标志、提示、搜索序号；最多八条 `place` 行依次为本次搜索选择键、名称、所属地区、纬度、经度。`weather-location-select key <选择键>` 只接受当前搜索仍有效的结果。`weather-location-set name <名称> latitude <纬度> longitude <经度>` 支持手动设置 WGS84 坐标，拒绝非有限数和超范围坐标；`weather-location-default` 恢复北京朝阳。地区保存后清除跨地区缓存并刷新，旧请求不能覆盖新地区。搜索不改配置，取消输入不提交变更；这些操作继续通过本机 Unix socket，不新增网络控制端口。

## 锁屏与壁纸库

提供的原生应用与系统输入法复用同一套锁屏覆盖层：保持原界面对象和编辑缓冲区，锁屏时拦截触控，短按电源键解锁后重新绘制；进入硬件休眠前也可上滑解锁。提醒优先于锁屏；停止提醒后回到锁屏，应用接收确认在解锁后展示。硬件休眠由后台独立协调，应用无需自行操作电源 sysfs。

后台维护全局闲置时间和锁定状态，避免父启动器等待子应用时丢失自动锁屏。`lock` 状态行依次为是否锁定、闲置秒数、锁定状态变更序号。`wallpaper` 行为本机 PGM 路径、标题、署名、缓存数、下载中标志和状态消息。图片为固定 600×800、8 位 P5 灰度格式，像素值量化为 16 阶。

`gallery` 状态行依次为模式（`daily` / `favorites` / `fixed`）、收藏数、当前图片 ID、固定图片 ID、目录 TSV 路径、目录修订号。空字段仍按现有约定写为 `-`。目录独立保存在 `/run/paperos/wallpapers.tsv`，避免较多收藏占满主状态行数上限；第一行为 `paperos-wallpapers-v1` 与修订号，以制表符分隔。后续 `photo` 行依次为 ID、原图路径、标题、署名、是否在近期缓存、是否收藏、是否为固定图片，布尔值为 `true` / `false`。目录在修订号变化时原子更新，客户端仅在修订号变化时重读。图片 ID 为 64 位小写十六进制；`<ID>.pgm` 是原图，`<ID>.thumb.pgm` 是 150×200 P5 缩略图。

命令 `lock-now` 手动锁屏，`lock-unlock` 解锁，`lock-activity` 报告用户操作，`lock-idle seconds 300` 保存闲置时间，`wallpaper-refresh` 请求后台更新图片。空闲时间为 0 时关闭自动锁屏；界面提供 60/180/300/600 秒选项。活动报告可每秒最多一次，不写持久闪存；绘图、网络完成或定时刷新不能作为用户活动。状态快照与命令继续使用现有本机接口，不开放新的远程控制端口。

壁纸库命令：`wallpaper-favorite id <ID> enabled true|false` 显式设置收藏状态；`wallpaper-use id <ID>` 将图片设为固定壁纸并切换到固定模式；`wallpaper-mode mode daily|favorites|fixed` 切换模式。收藏轮换必须已有收藏，每次从未锁定变为锁定时切换一次，重复锁定命令不再切换；固定模式保留最近固定的图片，没有固定记录时使用当前图片。最多七张近期缓存、64 张收藏和一张固定图片，按 ID 去重。索引与模式持久保存在服务数据目录 `lockscreen/index.json`，版本 2 兼容迁移版本 1；取消收藏后，既不在缓存也不被固定引用的文件才会删除。详情和全屏预览不调用上述变更命令，不修改用户选择。

直接接管屏幕的第三方应用也须接入此覆盖层和活动报告；当前锁屏不会强行抢占未接入的任意第三方程序。示例应用已经使用共享的原生模式。Windows 聚焦的下载、灰度转换、七张近期缓存、收藏保留和损坏校验由后台服务负责，应用无需联网下载壁纸。

## 硬件休眠

`sleep-enable enabled true|false` 保存电池供电时的自动休眠开关。接电是不可覆盖的休眠阻止条件：包括 USB 电源、充电器和电量已满的状态，自动及手动休眠都拒绝；供电状态不可读时也保持唤醒。`sleep-usb enabled true|false` 保留旧客户端的 USB 数据连接设置，但不能覆盖接电规则。`sleep-now` 在电池供电时请求先锁屏再立即休眠，允许覆盖自动关闭；当前有提醒或接收应用任务时拒绝。模拟器中的 `sleep-now` 返回不支持，不能用于模拟硬件验证。

`lock-powered-multiplier times 2|3|5|10` 保存接电时的自动锁屏倍数，旧配置默认为 5 倍。基础时长仍由 `lock-idle` 管理；关闭自动锁屏不因接电而开启。新增 `power` 状态行依次为：供电状态已知、已接电、倍数、当前生效的自动锁屏秒数；`lock` 行的时长继续表示基础值。接电或拔电后重新开始闲置计时，不改变当前锁定状态；拔电后已锁定的设备至少保持唤醒 15 秒。后台每秒检查独立的 AC/USB 供电传感器，不依赖五分钟电量采样或 USB 数据连接，准备交接和进入内核休眠前再次检查，插电取消不计作失败。

快照 `sleep` 行依次为：自动开关、硬件可用、阶段（`awake` / `preparing` / `resuming` / `error`）、消息、计划 RTC 唤醒的 Unix 时间、最近完成时间、最近实际休眠秒数、唤醒来源（`rtc` / `power-or-usb`）、周期号、USB 保持唤醒开关、当前 USB 数据连接标志。休眠时间通过 `CLOCK_BOOTTIME - CLOCK_MONOTONIC` 的差值测量，RTC 中断计数辅助确认定时唤醒；不能把 SSH 断线时长当作实际休眠时长。具体实现见 `services/sleep.go`、`services/suspend_linux.go`。

锁屏 15 秒后且没有提醒、传包或联网更新时，后台发起准备。原生应用必须在这一周期下完成黑、白、壁纸的 GC16 FULL 刷新并等待驱动完成，再把 `ready\t<周期>\t<锁定序号>\t<boottime秒>\t<pid>` 原子写入 `/run/paperos/sleep-display.state`。后台只接受同周期、同锁定序号、八秒内的确认，十秒内未收到则保留唤醒。现有原生应用与公共键盘共享实现，离线 `--render` 不产生硬件确认；自行接管屏幕的第三方应用须实现同样的交接，未接入时不会直接休眠。

独立子进程临时暂停 `/usr/bin/paperos` 的界面进程，关闭 Wi-Fi、USB 网络与 EPDC，保存并恢复原有电源参数，设置 `rtc0` 唤醒与内核 `wakeup_count` 握手，进入 suspend-to-RAM。到期提醒、短按电源键或 USB 事件可以唤醒；触控在真正休眠时关闭。恢复先放行界面及提醒，再恢复网络，不要求闹钟等待 DHCP。最近提醒前两秒唤醒，平时每 30 分钟唤醒一次更新数据；恢复后至少保持唤醒 20 秒。应用启动、解锁或电源键操作会取消尚未进入内核的准备。

周期结果保存在 `/var/lib/paperos/services/sleep-cycle.json`，临时交接文件位于 `/run/paperos/`。启动发现未完成周期会保存关闭自动休眠的配置，连续三次普通失败也会暂停自动休眠；用户可在电源设置重新开启。保留内存中的应用和编辑内容，不保存内存到磁盘，不修改内核或启动分区。

## 电量与续航统计

后台从 KT3 的 `bd7181x_bat` 容量及电源状态读取真实百分比，不解释未经确认的电流/电压单位。唤醒时每五分钟采样一次，休眠前后和正常停止服务时补采；不会为统计新增 RTC 唤醒。最近八个自然日的有界记录保存在 `/var/lib/paperos/services/battery/`，用于展示最近七天及边界区间。按 15 分钟及电源状态变化合并写入，文件原子替换。

快照 `battery` 行依次为：硬件可用、百分比、内核电池状态、已接电、采样 Unix 时间、历史 TSV 路径、修订号、消息。`native/services.h` 的 `paperos_battery_read()` 在修订号变化时读取历史。历史独立为 `/run/paperos/battery.tsv`，首行为 `paperos-battery-v1` 和修订号；后续 `summary`、`day`、`point` 行分别提供近 24 小时汇总、七个自然日和最多 145 个十分钟曲线点。充电点带接电标志，断档点不连线。

每条采样同时保存启动标识、墙上时间、BOOTTIME 和 MONOTONIC。重启、时钟跳变及超过 45 分钟的缺口不参与区间统计。实际休眠时长来自两种单调时钟差值；掉电按有效的未接电区间净百分点差统计，不作为电池健康度或剩余天数估计。休眠周期按启动标识和周期号去重，普通用户取消不记为失败。历史从安装此版本开始累积。

## 米家与远程家庭中枢

`org.paperos.mihome` 0.3.0 通过 NAS 专用只读网关读取选定的温度、湿度、空气指标和设备状态。小米官方 `XiaoMi/ha_xiaomi_home` 集成运行在 NAS 的 Home Assistant 中，由其完成米家 OAuth。HA 只导出管理员选定的值和单位，隔离容器提供兼容状态读取格式的接口；PaperOS 不持有 HA、米家或 NAS 登录凭据。

旧版直连使用过以下一次性授权向导；已迁移到只读网关的设备不应再次运行：

```powershell
python scripts/connect-mihome.py --server http://192.0.2.10:8123 --device 192.0.2.20 --open
```

旧向导仅监听 `127.0.0.1:8770`，OAuth 回调使用 `http://localhost:8770/` 同源地址，校验随机 state 与 CSRF；密码不经过向导。旧授权继承 HA 登录账户的权限，已替换为服务端白名单。迁移工具 `scripts/secure-mihome.py` 保留已有选择，为 NAS 生成令牌摘要与白名单，通过固定主机密钥的 SSH 将独立网关令牌送入 Kindle，确认新数据后撤销旧 HA 访问及刷新授权。

设备配置 `/var/lib/paperos/services/mihome.json` 为 0600，当前地址为 `http://192.0.2.10:8787`，只保存独立网关令牌、所选实体和本机代理，`RefreshToken`、`ClientID` 为空。`paperos-services import-mihome` 从标准输入读取配置，经 0600 Unix socket 的 `/mihome/config` 导入；不通过无线应用接收端口公开。唤醒时每两分钟至多自动读取一次，恢复联网后刷新；卸载米家应用后停止轮询。请求拒绝跨地址重定向，避免转发 Bearer 凭据。旧 OAuth 刷新代码只保留协议兼容，当前部署不使用 HA 授权。

网关仅接受有效令牌的 `GET /api/states/<白名单实体>`；未授权为 401，未选指标及文件/配置路径为 403，写入方法为 405。无上游转发或控制接口，容器不持有 HA 或 NAS 凭据，根文件系统及唯一指标目录挂载均只读。HA 每 30 秒导出数据，超过 90 秒未更新则网关返回 503，Kindle 保留旧读数与原时间。实现和部署见 [home_gateway/README.md](home_gateway/README.md)。

快照 `mihome` 行依次为：已配置、正在读取、最近成功时间、家庭名称、目录路径、修订号、消息。独立目录 `/run/paperos/mihome.tsv` 首行为 `paperos-mihome-v1` 与修订号；`item` 行依次为种类、标签、房间、值、单位、可用、缓存、时间、实体 ID。未取得数据、实体不可用和断网缓存均单独表示；缺失值不变成零。持久缓存不含授权，绑定不同账户或实体集合后不沿用旧值。

跨家庭网络可使用可选 Tailscale ARM 运行包：`scripts/fetch-tailscale.py` 校验官方归档，`scripts/build-tailnet-image.py` 构建独立 ext3 文件。设备上的 `/mnt/us/paperos/tailnet.ext3` 以只读方式挂载到 `/usr/lib/paperos/tailscale`，不写启动分区。`S46paperos-tailnet` 受 `/etc/paperos/tailscale.enabled` 控制，使用 userspace networking，仅提供 `127.0.0.1:1055` HTTP 代理；不替换系统 DNS 或内核默认路由。首次 `paperos-tailnet up --hostname=paperos-kt3 --accept-routes=true` 必须在浏览器授权设备加入用户的远程网络。中枢所在 NAS 的子网路由须已公布并获准；PaperOS 配置中的 `Proxy` 默认使用 `http://127.0.0.1:1055`。客户端通过 CONNECT 隧道透传原始请求，避免普通 HTTP 转发添加的头部触发 Home Assistant 的代理校验；不修改中枢的可信代理配置。未授权或远程网络不可达时保留缓存及原更新时间，不影响本机应用。

当前 Tailscale 访问策略已单独收紧：此 Kindle 的 IPv4/IPv6 地址只允许到 NAS 只读网关 TCP 8787，其余设备保留原有目标与端口权限。规则同时检查 Kindle 对后台、SMB、SSH 及 HA 原接口的拒绝访问，以及其他设备的 IPv4/IPv6 原权限。实际设备检查由 `scripts/audit-home-access.py` 调用 ARM 探针完成；只做连接和网关拒绝检查，不调用设备控制服务。

## 系统输入法

输入界面由 PaperOS 的公共服务 `paperos-inputd` 管理，开机自动启动。记事本和其他应用调用同一个接口，弹出同一套底部键盘，取得 UTF-8 文本；应用不需要实现自己的拼音、候选栏或按键界面。服务一次处理一个输入会话，支持中文、英文大小写、数字、符号、单行、多行和密码模式。

键盘按同版本原机 `zh_CN-600x800.keymap` 的尺寸和键位重排：底部 275 像素由 38 像素候选栏与 237 像素四行键区组成，正文编辑区可显示 14 行文字。拼音在光标处带下划线显示；取消、完成和光标左右移动位于顶部。`123` 切到数字页，`#+=` 切到符号页，`ABC` 返回字母页；中英切换与 Shift 大小写分别使用独立按键。中文模式提供逗号、句号和冒号。回车在多行输入中换行，在单行输入中确认。公共输入接口保持一致，应用无需为这个布局单独改造。

当前界面直接使用 framebuffer 和 evdev，尚未提供自动管理焦点的通用文本控件。原生应用在请求输入前需要停止绘图并释放触控，接口返回后重新取得触控并重画自己的界面。取消、输入服务不可用或键盘异常时，接口不修改应用的结果缓冲区。密码模式隐藏文字，不启动中文预测引擎。

C 应用使用 [native/input.h](native/input.h)；可编入 `native/input.c`，或链接与自己工具链匹配的 `libpaperos-input.a`：

```c
#include "input.h"

char edited[2048];
/* 应用先停止绘图、释放触控。 */
int status = paperos_input_text("编辑笔记", current_text,
                                PAPEROS_INPUT_MULTILINE,
                                edited, sizeof(edited));
/* 应用重新取得触控、重画界面。 */
if (status == PAPEROS_INPUT_ACCEPTED) {
    /* 使用 edited 更新应用内容；保存由应用决定。 */
}
```

默认是单行输入；`PAPEROS_INPUT_MULTILINE` 开启换行，`PAPEROS_INPUT_PASSWORD` 开启密码模式，`PAPEROS_INPUT_ENGLISH` 指定初始英文模式。密码和多行不能同时使用。输入上限由结果缓冲区容量决定，最多 8191 字节，不按汉字个数计算；记事本自身目前限制为 2047 字节。

Shell 应用可直接调用命令行客户端，示例 [examples/input-demo.papp](examples/input-demo.papp) 只包含清单和下列脚本：

```sh
#!/bin/sh
exec /usr/bin/paperos-input --title "独立应用 · 系统输入示例" \
    --multiline \
    --text-file "$PAPEROS_DATA_DIR/text.txt" \
    --output "$PAPEROS_DATA_DIR/text.txt"
```

`--text-file` 提供初始文字，文件不存在时按空文字处理。`--output` 在确认后以临时文件、fsync 和重命名写回，取消时保留原文件；不指定时输出到标准输出。退出码为 0（确认）、1（取消）、2（失败）。还支持 `--password`、`--english` 和 `--max-bytes 1..8191`。输入内容不通过命令行参数传递。

服务通过本机 Unix socket `/run/paperos/input.sock` 通信，接收标题、初始文字、模式和容量，返回状态与文本。源码为 `native/input.c`、`native/inputd.c`、`native/keyboard.c`，启动脚本为 `os/rootfs-overlay/etc/init.d/S55paperos-input`。当前客户端和服务限同一 UID 使用；这不是应用权限沙箱。公共服务此前已在真机通过中文输入、完成、保存、取消保留原文和返回启动器测试。紧凑布局已通过 KT3 模拟器中的原机引擎输入保存、独立 Shell 应用、触控交接和系统启动验证，并已部署真机；用户已确认本次布局的大小和键位可以，作为后续公共输入界面的基准。

### 原机组件的复用

公开的同版本固件中已找到 XT9 中文预测引擎 `libxt9zh.so.1.0`、中文 `libpredictor` 插件、词库，以及原机 600×800 的键盘布局。完整键盘程序 `kb` 依赖 `libkb`、GTK/X11、LIPC 和其他原机组件；预测插件依赖 glibc、GLib 与原机日志/IPC 库。

已经通过独立 ARM 兼容进程调用原预测插件：`nihao` 给出“你好”，`zhongguo` 给出“中国”，两者均可提交。此前记事本内的候选栏已通过真机中文选择、保存和重新打开测试；现在这部分由系统键盘统一提供。界面由 PaperOS 绘制，中文预测和词库来自原机组件。

`PAPEROS_IME_HELPER` 由系统输入服务使用，原引擎协议实现见 `native/ime.c`；应用通过公共输入接口调用即可。引擎使用自己的 GNU 运行库，与 musl 系统隔离；1.5 秒内无响应会结束兼容进程，系统键盘仍可使用英文模式。原机二进制和词库只在本地用于这台设备，不放入源码或对外发布的应用包。
