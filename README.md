# PaperOS for Kindle KT3

PaperOS 与原生应用以 GPL-3.0-or-later 开源。在线商店使用独立的公开
[应用仓库](https://github.com/ChrisPei/paperos-apps)：发现应用、下载、确认安装、检查更新，
并支持部分社区目录和压缩包格式。具体兼容边界与数据保留规则见 [STORE.md](STORE.md)。

给 Kindle Basic 2016 / 第 8 代（KT3 / Eanab）写的独立 Linux 用户空间和原生墨水屏应用。当前主页由应用提供 Widget：左侧时间来自闹钟应用，右侧日期和农历来自万年历；下方显示所选地区的逐小时天气（默认北京市朝阳区），以及米家室内指标和设备状态。米家需在电脑上完成家庭中枢授权，未配置时显示待连接状态。

PaperOS 已在这台真机上独立启动。PID 1 是自己的 BusyBox init，根文件系统来自自己的 ext3 镜像，原系统根目录已脱离运行环境；保留匹配的 3.10.53-lab126 内核。真机已验证正常重启自动进入 PaperOS、应用包和中文笔记保留，以及主动回到原系统后恢复 USB 调试与 Wi-Fi。日常打开、关闭和切换应用无需重启，也不再有临时测试的自动退出计时。

独立系统已在 KT3 QEMU 中从同版本 U-Boot / Linux 内核启动，并验证切换根文件系统、密钥登录、重启自动进入和系统镜像缺失时回退。600×800 显示、触控、独立应用、中文输入与保存此前均已通过真机交互测试。当前 Python/C 共运行 67 项测试（1 项私有引擎夹具测试跳过），其余通过；Go 后台服务通过竞态检测。KT3 内核模拟器另外验证了原机中文引擎、全屏黑白提醒、键盘输入恢复、后台服务故障恢复，以及加密传包的触屏拒绝、确认和安装。真机已验证无线驱动、扫描、关闭无线后的模块卸载、联网获取天气，以及无需 USB 的 TLS 应用接收和屏幕确认。用户已确认倒计时弹出、黑白切换、停止后返回万年历均正常；新版正常重启后，主页、后台服务和 Wi-Fi 自动恢复，程序摘要与部署版本一致。

界面、应用管理和公共键盘用 C 编写，后台计时、网络、天气与接收应用服务用 Go 编写，应用清单通过 Shell 指定入口。底部有“主页、应用、设置”三个入口；应用包格式、程序启动和数据接口见 [APP-SDK.md](APP-SDK.md)。原机中文引擎和词库通过独立 ARM 兼容进程工作；真机已验证拼音输入、选择“你好”、保存、返回面板再打开。记事本保留为独立应用，不占主页。

木鱼是独立离线应用：轻敲木鱼显示“功德 +1”和木槌反馈，记录累计、今日及本次次数，每次敲击自动保存；再次打开保留累计，跨天重置今日次数。支持系统锁屏、提醒及返回启动器，卸载后保留计数。运行 `wsl -d Ubuntu-24.04 -- bash /mnt/d/kindle/scripts/build-muyu.sh` 构建可安装的 `dist/muyu.papp/`；使用现有 Buildroot musl 工具链，压缩后的 ARM 程序约 201 KiB，启动时原子解压到应用私有目录。`examples/muyu.papp/` 是构建用清单和入口模板，需与编译出的程序一起打包。计数位于应用私有目录的 `merit.state`，实现见 `native/muyu.inc`。

电源管理支持 KT3 的 suspend-to-RAM：照片锁屏完成清屏后关闭无线、暂停界面并让硬件休眠，短按电源键唤醒；RTC 用于闹钟、倒计时和定期更新的唤醒。续航统计从安装本版开始记录真实电量、充电状态、休眠时间和唤醒来源，提供近 24 小时曲线及最近 7 天列表，不补造历史记录，也不为采样额外唤醒设备。米家通过 NAS 专用只读网关取得所选室内指标和设备状态，保留断网缓存及更新时间；小米官方集成运行在 NAS 的 Home Assistant 中。

2026-10-17 真机验证：NAS 的官方 Xiaomi Home v0.5.0 已完成用户授权并接入 26 台设备；Kindle 已保存所选 7 项温湿度、PM2.5 和功率指标，逐项与中枢源数据核对一致。后台服务重启后授权与选择保留，自动读取恢复；断开电脑的 Tailscale 后，Kindle 仍通过自己的 Tailscale 连接取得新读数。主页显示温湿度，米家应用分页查看全部指标。续航记录已包含真实 RTC 休眠和唤醒，当前充电区间不计作掉电；完整 7 天记录需随实际使用积累。

米家访问随后已完成服务端隔离：撤销并移除 Kindle 原 HA 访问与刷新授权，改用仅能读取这 7 项指标的独立网关令牌。Tailscale 仅允许 Kindle 访问 NAS 的 TCP 8787，真机已验证 NAS 后台、SMB、SSH、HTTP/HTTPS 和 HA 原端口均不能连接，而电脑仍可连接 NAS 后台、HA 和 SMB。其他设备原有权限及 SSH 策略保留。Kindle 后台和 Tailscale 进程重启后，7 项读数自动恢复，笔记、壁纸与提醒设置保留。网关隔离配置见 [home_gateway/README.md](home_gateway/README.md)。

“接收应用”同时支持局域网和 Tailscale 私网地址，换 Wi-Fi 后可继续使用同一个 Tailscale 地址发送；电脑和 Kindle 均需联网并处于获准互通的私网中。“设置 → Tailscale”显示本机名称、地址、版本和连接状态，提供私网连接及远程接收开关。接收仍需先开启十分钟窗口、在 Kindle 核对六位码并确认，包只进入应用库，安装另行选择。此入口不使用公网端口、Serve 或 Funnel，也不修改 NAS 只读访问策略；关闭远程接收不影响局域网接收。用法与协议见 [APP-SDK.md](APP-SDK.md)。

2026-10-19 真机已通过 Tailscale IPv4 完成万年历包发送、用户核对六位码并确认接收，接收文件与源文件一致。私网连接关闭及恢复、远程接收关闭时保留局域网接收均已通过；NAS 原只读限制、电脑原有 NAS 访问和 26 个应用、数据及凭据文件摘要保持。实际切换到另一 Wi-Fi 的漫游验证尚未进行。

无线推送的慢速上传已修复：原接收服务的 20 秒写入超时从读完请求头时开始计时，上传超过 20 秒后响应会被截断；现在写入时限覆盖 90 秒的完整上传预算及响应时间。真机同一组 24 秒慢传测试，修复前产生 TLS 错误，修复后正常返回协议响应。接收的十分钟窗口、证书固定、包摘要和屏幕确认保持不变。

Wi-Fi 支持多个保存的网络，附近列表标记已保存项，“已保存”页可无密码重连、重新输入密码或二次确认后忘记网络。修复了 `select_network` 后其他配置仍被禁用的问题，成功连接后启用所有保留网络、设置当前网络优先级并去除同名旧配置；认证失败保留旧凭据。切换到另一个保存网络时重新获取 DHCP 地址，密码只保留在本机受限的无线配置中。真机已保留两个不同网络并验证当前网络无密码重连；另一个网络当前不在附近，实际跨网络切换尚未验证。

系统输入法作为公共服务，应用请求输入时使用同一套键盘，确认后收到文字，取消保留原文；支持中文、英文大小写、数字、符号和密码。布局已按原机 600×800 键盘重排为底部 275 像素，正文区可显示 14 行文字；取消和完成位于顶部，拼音在光标处显示。紧凑布局已在 KT3 模拟器通过两种应用共用键盘、中文保存、触控交接、自动重启和回退验证，并已更新真机，笔记和应用数据保留。此前公共服务已经通过真机功能测试，用户也已确认本次布局的大小和键位可以。C 与 Shell 接入示例见 SDK；应用不必各自实现键盘。

## 目录与产物

《复苏的逆转》NDS 汉化版现作为独立 `.papp` 游戏接入。它在 Kindle 本机运行，双屏两倍显示，下屏直接触控，侧栏提供按键、刷新和模拟吹气；支持即时存档、保存退出和重新进入恢复。游戏 ROM 单独导入，程序包不含游戏本体。已验证标题、章节选择、第一话部分中文对白、原生 `.dsv` 保存后跨进程读取，以及游戏界面的锁屏与恢复；尚未完成全篇及第五话特殊交互验收。源码、构建和验证边界见 [native/nds/README.md](native/nds/README.md)。

| 路径 | 内容 |
|---|---|
| `native/paperos.c`、`native/dashboard.inc` | C 原生主页、Widget、应用、触控、提醒和设置 |
| `native/calendar.c`、`native/lunar-data.h`、`native/solar-terms-data.h` | 离线农历、节日和 1901–2100 年二十四节气 |
| `native/services.c`、`services/` | 原生状态接口与 Go 后台计时、网络、天气、TLS 接收服务 |
| `native/input*.c`、`native/keyboard.c` | 公共输入接口、服务、命令行客户端和统一键盘 |
| `bridge/bridge.py` | 电脑端状态服务；只读本地适配器和经过认证的通用 JSON 推送 |
| `os/` | Buildroot 外部工程、BusyBox init、设备节点、匹配驱动和启动脚本 |
| `device-probe/` | 原机硬件探测、USB 调试入口和保留原 init 的启动包装 |
| `dist/paperos-kt3` | ARMv7 soft-float 静态程序，使用电脑端交叉编译器生成 |
| `dist/paperos-kt3-rootfs.ext3` | 256 MiB 的独立 musl Linux 根文件系统 |
| `dist/paperos-kt3-rootfs.tar` | 根文件系统归档；保留设备节点与 root 属主 |
| `preview/` | 从真实 C 程序及模拟器生成的画面 |
| `build/rea/` | REA 静态分析证据、分析前后摘要 |
| `sources.lock.json` | Buildroot、FBInk、QEMU、KindleTool 的固定源代码版本 |

首版保留与硬件配套的 3.10.53-lab126 Linux 内核，自己构建并引导用户空间；界面不依赖亚马逊 framework。显示、触控模块取自同版本公开参考固件，真机镜像使用这台设备备份的面板波形。模拟器使用内置显示波形和合成设备身份。

新版镜像包含匹配的 Broadcom Wi-Fi 驱动、固件、CA 证书及 DHCP 启动脚本。可在 PaperOS“设置 → Wi-Fi”扫描、选择网络并通过公共键盘输入密码；支持开放网络与 WPA 个人网络，暂不支持企业认证。连接配置仅保存在设备。关闭无线或开启飞行模式会停用无线和应用接收；启动脚本先读取保存的开关状态，再决定是否加载无线模块。可还原的原系统 OTA 停用和 USB 调试自动启动已安装并经重启验证；`scripts/device-development-setup.py --restore` 根据保留的逐文件摘要恢复。

## 使用启动器

开机后进入 Widget 主页。点击时间、日历、天气或米家卡片打开对应应用，点“返回主页”退出。底部“应用”列出已安装应用和接收的应用包，可安装、更新或确认卸载；卸载会移除应用和对应主页组件，保留用户数据。“设置 → 首页组件”可添加、隐藏或调整组件顺序；隐藏组件不会卸载应用。

顶部状态栏左侧保留小号 PaperOS 标识，右侧统一显示刷新、网络和电池图标，不再放置“编辑”“锁屏”等文字按钮。网络图标区分连接、断开和飞行模式，电池按电量填充并在充电时显示闪电；点电池图标或“设置 → 电量与续航”可查看统计。首页组件编辑从“设置 → 首页组件”进入。

点击顶部圆形刷新图标执行一次全屏 GC16 闪烁刷新，并等待屏幕驱动完成，用于清理翻页或界面切换后的残影。当前页面和组件顺序保持不变；它不需要联网或重启。完成状态记录在临时文件 `/run/paperos/display-refresh.state`，不写用户数据。

闲置默认 5 分钟后显示照片锁屏，也可短按电源键，或在“设置 → 锁屏与壁纸”点“立即锁屏”。再次短按电源键解锁，回到原应用或输入法，保留正在编辑的文字；尚未休眠时也可向上滑动至少 80 像素解锁。电源键监听这台 KT3 实测的 bd7181x 内核 uevent，检查内核来源、设备路径、事件类型和序号，过滤重复与抖动；不改动长按的硬件行为。普通点按不会穿透锁屏。“设置 → 锁屏与壁纸”可关闭自动锁屏、选择 1/3/5/10 分钟、立即锁屏或更新图片。锁屏不暂停闹钟与倒计时；停止提醒后仍回到锁屏，接收应用的确认页在解锁后显示。当前没有密码锁。

“设置 → 锁屏与壁纸 → 电源与休眠”提供电池供电时的自动休眠、接电锁屏倍数和立即休眠。接充电器或 USB 电源时，自动锁屏默认为原时长的 5 倍，可选 2/3/5/10 倍；默认 5 分钟因此变为 25 分钟。充满电仍按接电处理，始终阻止自动及手动硬件休眠；短按电源键照常锁屏、解锁，关闭自动锁屏的设置继续有效。拔电后恢复原来的时长和休眠开关，并重新开始闲置计时；已经锁定时保持锁定，至少等待 15 秒才考虑休眠。后台每秒检查供电，准备过程中插电会取消，电源传感器不可读时也保持唤醒。电池供电时，自动休眠默认在锁屏 15 秒后开始，接收应用、传包、提醒和联网更新期间保持唤醒。“立即休眠”在电池供电时可覆盖自动休眠关闭。准备休眠时重新完成纯黑、纯白、壁纸三个阶段，驱动确认画面完成后才关闭屏幕控制器；墨水屏保留照片和标为“休眠时刻”的时间。真正休眠后触屏不负责唤醒，请短按电源键。

2026-10-17 接电策略已部署到真机：临时用 1 分钟基础时长验证 5 倍规则，第 70、185 秒未锁定，第 304 秒已锁定，第 326 秒仍保持唤醒；测试时旧 USB 调试防休眠开关关闭。满电接电状态下，手动休眠和独立休眠子进程均拒绝执行。测试后恢复基础 5 分钟、接电 25 分钟，后台重启后设置保留，笔记、壁纸、只读米家授权与提醒设置未变。新规则下的实体拔电过程本次未重测，拔电恢复及准备中插电取消由状态机测试覆盖。部署摘要、备份位置和观测记录在本地 `build/external-power-device-validation.json`。

休眠前卸载 Wi-Fi、USB 网络驱动并提前关闭 EPDC 屏幕控制器，避免这台 KT3 驱动在内核冻结工作队列时卡住；驱动按串行方式进入 `mem` 状态。唤醒后恢复屏幕、触控、USB 与原来的无线开关状态，再连接已保存的 Wi-Fi。休眠期间无法接收无线传包或 SSH；开启“接收应用”会阻止休眠。RTC 采用主 PMIC 的 `rtc0`，在最近的闹钟、倒计时或稍后提醒前两秒唤醒；没有近期提醒时每 30 分钟唤醒更新，处理完成后再次休眠。倒计时使用包含休眠时间的启动时钟，不因校时改变剩余时长。这里实现的是保留内存的休眠，没有实现保存内存到磁盘后断电的休眠。

休眠周期先保存未完成标记，成功返回后记录实际休眠秒数和唤醒来源；若设备在过程中重启，下次启动会暂停自动休眠，避免反复重启。普通失败保留唤醒状态，连续三次失败暂停自动休眠。“电源与休眠”页可查看最近结果并重新开启。真机集成测试测得一次实际休眠约 36 秒，RTC 中断计数递增、倒计时提醒送达且启动标识未改变，随后 Wi-Fi 与 USB 网络驱动恢复。 用户随后确认拔掉 USB 后短按电源键唤醒、返回界面和触控正常；对应记录测得约 453 秒实际休眠，RTC 中断计数未变、启动标识未变，Wi-Fi 恢复。实现与状态接口见 SDK 的“硬件休眠”部分。

每次进入照片锁屏（包括锁定状态下重启界面、从提醒返回、每日更换照片）均依次全屏显示纯黑、纯白、最终壁纸，三个阶段都使用 GC16 FULL 并等待驱动完成后再继续，避免上一个页面残留在照片上。锁屏时钟的普通分钟更新不重复该清理流程。每轮结果原子写入 `/run/paperos/lock-refresh.state`，包含黑、白、壁纸三个阶段的驱动返回码；检测依据是上一次实际绘制的画面，覆盖直接通过设置锁屏的入口。

“设置 → 锁屏与壁纸”显示当前壁纸缩略图，点“浏览壁纸与收藏”查看图片列表和“我的收藏”。点图片进入详情，可左右翻图、收藏或取消收藏、设为固定壁纸；再点大图查看带时间和日期的全屏锁屏效果，点任意位置返回。浏览和预览不会改变当前壁纸。

壁纸模式可选“每日换图”“收藏轮换”“固定一张”。每日换图按北京时间每天选择一张，断网使用最多 7 张近期缓存；收藏轮换在每次真正进入锁屏时换到下一张收藏，跨天不会自行更换；固定一张长期保留所选图片，只有主动更改才会切换。收藏最多 64 张，与七张近期缓存分开保留，固定图片也单独保留；后台更新、缓存淘汰和重启不会删除它们。取消收藏仅移除收藏标记，仍在近期缓存或仍被固定选用的图片继续保留；没有收藏时不能启用收藏轮换，取消最后一张收藏会恢复每日换图。

壁纸从微软 Windows 聚焦的竖版图片源获取。首次填充会查询多个地区的聚焦图片池，不把它们标成过去七天的历史图片；每日模式同一天保持选中的图片，断网或更新失败保留缓存。照片保留署名，在设备端裁剪、缩放并抖动到 600×800、16 阶灰度，每张约 480 KB，并生成 150×200 的约 30 KB 缩略图，七张照片及缩略图约 3.6 MB。同一张图片的缓存、收藏和固定引用共用文件。索引版本 2 保存模式、收藏、固定图片及 SHA-256，并兼容迁移旧索引；文件在服务数据目录的 `lockscreen/` 中。重新启动服务会校验图片、重建缺失缩略图、剔除损坏图片，并保留当前运行期间的锁定状态。

Windows 聚焦没有微软承诺稳定的公开图片 API；接口路径和嵌套响应格式参考 [ORelio / Spotlight Downloader 的接口研究](https://github.com/ORelio/Spotlight-Downloader/blob/master/SpotlightAPI.md)，下载与缓存代码独立实现。只访问微软图片接口和图片 CDN，不发送展示或点击追踪请求。接口变化时已有缓存仍可使用；微软关于聚焦背景的说明见[官方文档](https://learn.microsoft.com/en-us/windows/configuration/windows-spotlight/)。

闹钟应用支持设置系统日期和时间、最多 8 个闹钟、单次或按星期重复，以及可暂停、继续、取消的倒计时。提醒会覆盖当前 PaperOS 原生应用或键盘，每 2 秒黑白切换；“停止”恢复原界面，“稍后提醒”延后 5 分钟。后台服务独立运行并保存状态，切换应用不影响计时；监视进程会在服务异常退出后重新启动它。卸载闹钟应用会取消它的后台提醒。

“设置 → 设置时间”默认开启自动对时：连上 Wi-Fi 后同步，以后每 6 小时校准，也可点“立即同步”；断网时显示等待联网，服务器失败后间隔 5 分钟重试。时间来源为[阿里云公共 NTP 服务](https://help.aliyun.com/en/ecs/user-guide/alibaba-cloud-ntp-server/)，依照 [SNTPv4](https://www.rfc-editor.org/rfc/rfc4330.html) 验证回复来源关联、同步标志、层级和服务器时间。同步成功后写入硬件时钟，显示同步时间并保存开关。关闭自动对时后可手动设置；两种校时都会保留倒计时的剩余时长，并重新计算闹钟的下次时间。当前 KT3 的 32 位内核时钟仍受 2038 年范围限制。

天气通过经 CA 校验的 HTTPS 获取 [Open-Meteo](https://open-meteo.com/en/docs) 数据，每 30 分钟更新，也可手动刷新。显示当前温度、最高最低温，以及逐小时天气、降水概率和风速；断网保留缓存并标注更新时间。默认地区为北京市朝阳区。打开天气应用右上角“地区设置”，用统一中文输入法搜索国内城市或区县，核对结果中的所属省市后点选保存；也可按“杭州,浙江”限定省市。搜索同时考虑带“市/区/县”后缀和去掉后缀的名称，将完整地名匹配排在较长的前缀名称之前。地区查询使用 [Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api)，地名数据来自 GeoNames。来源对部分区县收录不完整，右上角“手动设置”可填写名称及 WGS84 经纬度，也可恢复北京朝阳预设。

选定地区会更新天气应用和首页卡片，并持久保存；输入取消或返回不会改变已保存地区。切换地区立即移除旧地区预报，联网时请求新预报，断网时等待联网；后台取消旧请求，并校验请求所属地区和序号，避免旧地区数据覆盖新地区。单纯刷新失败继续保留同地区的缓存。搜索结果仅在内存中保留，旧搜索的选择键失效后会要求重选。Open-Meteo 免费服务按其[个人非商业使用条款](https://open-meteo.com/en/pricing)使用。

万年历离线显示二十四节气、公历节日、春节、元宵、端午、中秋、重阳和除夕等农历节日，以及母亲节、父亲节。月历优先显示节日或节气名称；同日有多项时用小点提示，选中日期后显示完整名称。普通日期显示下一个节气及相距天数；主页日期组件也会显示当天的特殊日期。除夕按下一天是否为正月初一判断，闰月不重复标记传统节日。

节气日期采用[香港天文台公历与农历对照表](https://www.hko.gov.hk/tc/gts/time/conversion.htm)（UTC+8），覆盖 1901–2100 年共 4800 项日期；来源和原始内容 SHA-256 记录在 `assets/solar-terms-sources.json`。`scripts/generate-solar-terms.py` 校验每年 24 个节气后生成 C 数据表，Kindle 不需要联网查询。节日使用常见的现代日期规则，不包含逐年发布的放假调休安排。

无线传入自己的应用：让电脑与 Kindle 连接同一局域网，在 Kindle“设置”中开启“接收应用”（10 分钟有效），首次运行 `python scripts/push-app.py examples/alarm.papp --host <Kindle的Wi-Fi地址>`。电脑和 Kindle 都会显示六位校验码；核对一致后在 Kindle 点“确认接收”，再到“应用 → 接收的应用包”安装。设备自动生成 TLS 证书，电脑在本次确认成功后记住证书；无需手工管理密钥。接收不会自动安装或运行程序。

成功配对后，把整个 `.papp` 目录拖到 `send-app.cmd` 会默认通过 Wi-Fi 发送，仍需设备端确认。IP 改变时重新指定 `--host`。也可保持 USB 连接，运行 `python scripts/push-app.py examples/alarm.papp --usb` 使用已有的密钥调试通道；传入的包出现在同一个应用库中。发送和接收两端都会检查包大小、目录及摘要。

PaperOS 运行时 USB 使用网络连接，不能把包含正在运行系统镜像的存储同时导出为 Windows 磁盘。`scripts/connect-device-usb.ps1 -Port 22` 会连接已配置的设备；原系统调试使用端口 2222。SDK 见 [APP-SDK.md](APP-SDK.md)。

## 真机引导与回退

完整 3909091328 字节 eMMC 用户区、boot0/boot1 已备份并通过 SHA-256 校验。实际安装保留了原 `/sbin/init`，在其入口加入静态引导器；独立系统是用户存储中的普通 `paperos/system.ext3` 文件。没有改写分区布局、内核、U-Boot 或 IDME 启动模式。

引导器在切换系统前清除 `boot.enable`。独立系统首次启动需在三分钟内确认，否则重启回到保留的系统；验证成功后启用自动进入。后续启动通过界面与恢复服务的检查后重新设定下一次启动标记。模拟器验证了镜像缺失的回退路径；真机验证了关闭启动标记后回到原系统、重新启用后再次独立启动。

相关代码为 `native/bootstrap.c`、`scripts/device-bootstrap.py` 和 `os/rootfs-overlay/usr/sbin/paperos-boot-guard`。部署脚本要求完整备份、匹配的模拟器验证、逐文件摘要和密钥连接。设备私有镜像与验证报告位于忽略的 `build/` 目录。

## 构建与验证

构建环境是 Windows + Ubuntu-24.04 WSL，编译目录放在 WSL Linux 文件系统 `~/kindle-build`，项目源代码在 `D:\kindle`。第一次构建工具链需要较长时间。

```powershell
python scripts/fetch-sources.py
python scripts/fetch-assets.py
wsl -d Ubuntu-24.04 -u root -- bash /mnt/d/kindle/scripts/setup-host.sh
wsl -d Ubuntu-24.04 -- bash /mnt/d/kindle/scripts/build-native.sh
python scripts/render-preview.py
```

独立系统还需先通过 `scripts/fetch-recovery.py` 下载公开的 KT3 5.16.2.1.1 参考固件，使用已构建的 KindleTool 解包到 `~/kindle-build/recovery-kt3`，并解压 `rootfs.img.gz`。公开固件不是这台设备的完整恢复备份。

```powershell
wsl -d Ubuntu-24.04 -- python3 /mnt/d/kindle/scripts/import-kt3-drivers.py
wsl -d Ubuntu-24.04 -- bash /mnt/d/kindle/scripts/build-rootfs.sh
wsl -d Ubuntu-24.04 -- bash -lc 'cd /mnt/d/kindle && python3 -m unittest discover -s tests -v'
```

后台服务仅使用 Go 标准库，`build-native.sh` 和 `build-rootfs.sh` 会先准备并构建它。工具链固定在 `services/toolchain.json`；`scripts/fetch-go.py` 将固定摘要与官方发布记录比较后下载、校验 Linux 工具链，安装路径记录在私有构建目录 `build/go-toolchain.json`。可在 `services/` 中用该工具链执行 `go test -race ./...`。

新主页的实际 C 渲染预览由 `scripts/render-dashboard.py` 生成。`scripts/test-bootstrap-emulator.py --dashboard` 会在 KT3 内核中验证组件启动、中文输入被提醒中断后恢复、黑白切换、停止和稍后提醒、服务恢复，以及触屏确认后接收和安装应用。模拟器使用明确启用的测试网络；真实无线扫描和模块卸载由 `scripts/probe-paperos-wifi.py` 单独验证。

根文件系统通过 Buildroot fakeroot 生成；不要把解包后的文件直接用普通用户权限重新打包为刷机镜像。构建脚本保留上一个 ext3 镜像，以便比较和回退。

`scripts/normalize-source.py` 在 Linux 构建副本中恢复 Windows Git 可能检出为普通文本的符号链接，并规范文本换行。它仅接受这个工程固定的 Buildroot / QEMU 构建路径。

## 状态面板

本机运行：

```powershell
python bridge/bridge.py
python bridge/bridge.py --export preview/live-agents.tsv
```

电脑端提供 `GET /v1/agents`（JSON）、`GET /v1/agents.tsv`（原生界面协议）和 `POST /v1/agents`。推送只接收 `id`、`source`、`title`、`state`、`updated_at` 这些状态元数据，不提供执行命令接口。合法状态：`running`、`waiting`、`completed`、`failed`、`idle`、`stopped`、`unknown`。活跃状态超过 5 分钟没有更新会变为未知，不会当作已完成。

Codex 适配器以 SQLite 只读模式获取本机任务标题，再从有界的事件尾部推断状态。输出标注 `inferred-from-local-events`；这不是桌面应用运行时状态的完整接口，也不会自动取得远程 Mac 上的所有任务。不会导出对话正文、工具参数、认证文件或私有文件路径。

Cowork 适配器支持本地 session 元数据。目前这台电脑尚未找到可用的 Cowork session 记录，因此初始画面中的 Cowork 任务是明确标注的示例。可用自己的 agent hook 通过 `bridge/publish.py` 推送真实状态：

```powershell
python bridge/publish.py --url http://127.0.0.1:8086 --token-file bridge/local-token.txt --id example-task --source Cowork --title "整理工作资料" --state running
```

给 Kindle 提供局域网服务时，生成至少 24 字符的随机 token，保存在本地文件，并明确绑定电脑的局域网 IPv4 地址：

```powershell
python bridge/bridge.py --bind <电脑局域网IPv4> --token-file bridge/local-token.txt
```

然后配置 Kindle 的 `/etc/paperos.env`：

```sh
PAPEROS_BRIDGE_URL=http://<电脑局域网IPv4>:8086/v1/agents.tsv
PAPEROS_BRIDGE_TOKEN=<同一个token>
```

不要把 token 提交到仓库。此原生客户端当前只支持 IPv4 HTTP，适用于已确认的可信本地连接。默认服务只监听回环地址；局域网读取和所有状态推送均要求 token。刷新间隔 5 秒，墨水屏仅在内容或分钟变化时更新。

## 记事本

记事本是 `org.paperos.notes` 独立应用，笔记存于应用数据目录 `.data/org.paperos.notes/note.txt`。保存采用临时文件、fsync 和原子替换，卸载时保留数据。点击文字区域或“编辑文字”调用系统输入法；中文候选由公共服务中的原机预测引擎提供。点“完成”将文字交回记事本，再点“保存”持久化；点“取消”保留原文。首版笔记容量为 2047 字节，系统编辑器支持移动光标和跟随光标显示文字。

## KT3 模拟器

使用 `sources.lock.json` 中固定的 e-ink QEMU 源代码构建 `arm-softmmu`，产物路径为 `~/kindle-build/qemu-eink/build/qemu-system-arm`。公开参考固件提供同版本 `u-boot.bin` 和 `uImage`。以下操作只读写 `~/kindle-build/paperos-emulator/` 下的普通磁盘文件：

```powershell
wsl -d Ubuntu-24.04 -- python3 /mnt/d/kindle/scripts/prepare-emulator.py
wsl -d Ubuntu-24.04 -- python3 /mnt/d/kindle/scripts/prepare-emulator.py --start
wsl -d Ubuntu-24.04 -- python3 /mnt/d/kindle/scripts/emulator-control.py status
wsl -d Ubuntu-24.04 -- python3 /mnt/d/kindle/scripts/emulator-control.py capture --name emulator-home
wsl -d Ubuntu-24.04 -- python3 /mnt/d/kindle/scripts/emulator-control.py tap --x 150 --y 440
wsl -d Ubuntu-24.04 -- python3 /mnt/d/kindle/scripts/emulator-control.py stop
```

更新后先停止模拟器，再 `prepare-emulator.py --rebuild`；旧测试磁盘会保留。启动日志为 `~/kindle-build/paperos-emulator/serial.log`，输入摘要为同目录 `inputs.json`。

## REA

[REA](https://github.com/morluto/rea) 已用于 ARM ELF 的静态分析。`scripts/analyze-rea.sh` 固定 `rea-agents@6.5.0`、Node 24 LTS 和 ARM GNU objdump，保存原始结果及 SHA-256。REA 当前的公开固件分析能力属于离线分析，不承担 Kindle 越狱、刷写或真机驱动控制。260 MiB 的整包也超过其固件检查 128 MiB 输入上限，因此公开固件由 KindleTool 解包后再分析具体文件。

## 真机安装前的必要事实

probe v3 已取得：root、ARMv7、3.10.53-lab126、约 512 MiB RAM，eMMC 用户区 3909091328 字节；p1 起点 65536 扇区、450 MiB，p2/p3 各 64 MiB，p4 从 1249280 扇区开始，3269459968 字节。显示模块为 mxc_epdc_fb / mxc_epdc_eink，触控为 zforce2。完整用户区、boot0/boot1、IDME 所在区域和设备波形已经保存；安全 RPMB 未改变或采集。原系统 USB 显示的 `G:` 是 p4 的导出视图，PaperOS 使用 USB 网络。fastboot 恢复端点尚未验证，工程没有据此提供裸设备刷写命令。

本机的 p2 已被用作新主页的数据分区，没有 `/sbin/init`，不能盲目执行 `idme --bootmode diags`。两个备份内核均未启用 KEXEC。`scripts/test-recovery-boot-emulator.py` 只在新的普通磁盘文件中创建恢复系统，使用备份内核和合成设备身份验证 p2 启动；不写物理设备。

`scripts/backup-usb-partition.ps1` 已完成 p4 原始备份，读取时锁定 Windows 卷并校验保存后的 SHA-256。`native/recovery-snapshot.c` 在对应内核的 KT3 模拟器中验证了两个 64 MiB ext3 文件系统的短暂冻结、RAM 快照、解冻，以及 e2fsck 和文件内容检查。`device-probe/bin/backup-system.sh` 保存 610 MiB 启动/系统前缀、独立的 p2/p3 一致快照、boot0/boot1 和私有波形；所有 eMMC 句柄只读，并临时防止休眠。真机上旧工具的预检查曾出现 `Segmentation fault`，具体崩溃命令尚未确认；新版启动器先把静态 ARM musl 工具复制到 RAM，安装局部命令链接，再运行带逐步日志的预检查和独立后台任务。`scripts/build-backup-toolbox.sh` 从固定 Buildroot 的 BusyBox 1.38.0 下载构建有限工具集，校验源归档；`scripts/test-backup-toolbox-emulator.py` 已在 3.10.53-lab126 上验证压缩、打包、摘要、大文件、后台任务，以及预检查和分区信息拒绝条件。`scripts/stage-system-backup.ps1` 要求快照助手和静态工具的对应内核验证通过，且当前摘要与验证记录一致。`scripts/collect-system-backup.py` 校验设备摘要、检查 MBR、组合完整用户区镜像。备份只保存在忽略目录，不发布设备身份与账户数据。

旧入口修复的参考来源是 [NiLuJe 的 hotfix 说明](https://www.mobileread.com/forums/showpost.php?p=3004892&postcount=1597) 与 [作者的下载索引](https://www.mobileread.com/forums/showthread.php?t=225030)。`scripts/fetch-launcher-repair.py` 仅下载解包，不安装。hotfix 会更新越狱 bridge、开发证书、root helper 和搜索脚本入口，并重写 `mkk` / `rp` 备份；实际使用前要保存现有内容。KUAL 更新应使用 coplate Booklet 版本和 MRPI，不能依靠替换那个零字节的 `KUAL.kual` 文件修复。

这台设备重启后搜索入口仍失效，hotfix 手动更新也失败，`mkk` 内容未更新。后续采用 [WinterBreak](https://kindlemodding.org/jailbreaking/WinterBreak/) 的 nativeBridge 执行入口，先做只读探测。`scripts/fetch-winterbreak.py` 下载 v2.1.0，摘要与 GitHub 发布的 SHA-256 一致；`scripts/prepare-probe-entry.py` 复用其 Mesquito 入口并创建 **PaperOS hardware probe** 应用。这个派生应用的命令仅为 `/bin/sh /mnt/us/extensions/PaperOSProbe/bin/probe.sh`；上游通过网络安装 jailbreak 的应用不复制到设备。

`scripts/backup-userstore.py` 私下备份并校验 USB 可见文件；已保存 5774 个文件、491802996 字节。这仍不是完整 eMMC 备份。`scripts/stage-probe-entry.ps1` 要求完整备份，校验覆盖前的原文件、复制后的摘要，并在用户存储建立临时 `paperos-update-guard` 占位文件，留下约 80 MiB。该入口执行后应从 USB 用户存储读取 `paperos/device-probe.txt`，再决定 root 恢复、设备备份和独立系统安装步骤。

用户确认这台 Kindle 没有商店入口，因此 WinterBreak 路径不可用。已准备离线 LanguageBreak **1.0.2.1**（作者发布包 `LanguageBreak-16.11.23.tar.gz`），并记录 SHA-256 `b995cd6c687d007a166f0459dbb39d75de32a24e85be09fe3d911a0eb3736b5f`。这份旧发布没有 GitHub 官方 digest 字段；该摘要是本地观测值，不是额外的官方完整性验证。简体中文 hotfix 的设备表包含 Kindle Basic 2 (2016)，OTA 范围包含当前固件修订号。

**用户已明确允许清空设备，继续离线方案。随后旧桥恢复并取得 root，当前没有必要清空或继续 LanguageBreak。** 首轮 LanguageBreak 载荷未复制，也未执行清除设备。原商店缓存和临时占位文件已恢复；演示模式中产生的崩溃报告已私下备份。USB 曾显示 No Media / 0 字节，经手势进入主页并执行 `;uzb` 后恢复访问。

完整 eMMC 和启动区备份已完成。含原机波形、原中文输入引擎、设备 SSH 密钥和开机启动器的私有镜像保存在忽略的 `build/` 目录。真机已通过普通镜像文件独立启动，并保留原系统作为回退路径。一次性 fastboot 请求未得到预期恢复端点，因此没有使用 fastboot 刷写，也没有设置持久 fastboot/diags 模式。

`scripts/watch-languagebreak-usb.ps1` 是清空阶段第二次复制的单次等待脚本：先检测 USB 断开，再校验同一设备的 USB 身份摘要，重新连接时复制并校验 6 个载荷文件；它本身不执行清空或刷写。源文件、状态授权和脚本预检查已通过，目前未启动等待脚本。

此离线路径不需要商店或 Wi-Fi。流程为演示模式 → sideload 载荷 → Resell Device（清除数据）→ 再次复制载荷 → 选择简体中文 → 安装 LanguageBreak 专用 hotfix → 恢复脚本入口后读取实际硬件并备份 eMMC。应先阅读 [作者的对应说明](https://github.com/notmarek/LanguageBreak#installation)，不能把更高固件或其他越狱的安装包混入这个流程。

## 来源与许可

PaperOS 源码为 GPL-3.0-or-later，FBInk 为 GPL-3.0-or-later；字体是 Noto Sans CJK（OFL），stb_truetype 使用其上游双许可。匹配驱动的逐文件来源、摘要及模块许可保存在 `build/kt3-drivers/sources.json` 和镜像内 `usr/share/paperos/driver-sources.json`；EPDC companion 标为 proprietary。因此当前本地验证镜像不等于可任意分发的纯开源系统。公开原厂固件、私有设备备份、token、编译工具和生成产物不纳入源码仓库。
