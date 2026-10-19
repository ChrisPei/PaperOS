# PaperOS 米家只读出口

NAS 的 Home Assistant 保留官方 Xiaomi Home 集成。`paperos_export` 只从内存读取管理员选定的状态，每 30 秒把值和单位写入一个专用目录。独立网关容器只读取这个目录，不持有 Home Assistant、米家或 NAS 登录凭据，也不连接上游服务。

Kindle 只保存网关的独立随机令牌，NAS 只保存令牌的 SHA-256 摘要。迁移完成后撤销旧版 Kindle 的 HA 访问及刷新授权。取得网关令牌也只能读取 NAS 白名单内的指标。

## 接口边界

| 请求 | 结果 |
|---|---|
| 正确令牌，`GET /api/states/<所选实体>` | 200，仅实体 ID、值和单位 |
| 无令牌或错误令牌 | 401 |
| 未选指标、列表、配置、文件或代理路径 | 403 |
| POST、PUT、PATCH、DELETE 等写入方法 | 405 |
| 导出文件缺失、损坏或超过 90 秒未更新 | 503，Kindle 保留旧读数及原时间 |

服务没有控制设备、浏览文件、修改目录或转发任意 URL 的接口。白名单在 NAS 上加载，Kindle 不能通过请求扩大它。改变所选实体需要 NAS 管理员修改 `scope.json`，重新加载导出组件和网关，并同步 Kindle 的显示配置。

## NAS 部署

- HA 组件：`/config/custom_components/paperos_export/`，在 `configuration.yaml` 添加 `paperos_export:`。组件不提供 HTTP 服务，不调用 `hass.services`。
- 导出目录：`/config/paperos-readonly/`，宿主机对应 `/volume1/docker/paperos-readonly/`。只放 `scope.json`、`export.json` 和 `gateway.py`，不放 HA 配置或授权。
- 独立项目：`paperos-readonly`，目录为 `/volume1/docker/paperos-readonly-project/`。配置见 [compose.yaml](compose.yaml)。
- 容器使用普通用户 `1000:10`，以适应该 NAS 的共享文件夹 ACL；根文件系统只读，仅挂载 `/data` 且只读，移除全部 capabilities 并启用 `no-new-privileges`，不挂载 Docker socket。
- NAS 仅在 LAN 地址的 TCP 8787 发布接口。本次没有增加公网端口映射、Funnel 或反向代理规则。

新 NAS 的目录及普通用户 UID/GID 须按实际情况调整，不应改用 root 或挂载整个 HA 配置目录解决权限问题。令牌摘要不能当作 Bearer 令牌使用。

## 网络隔离

Tailscale 只允许此 Kindle 连接 `192.0.2.10:8787/tcp`。原有全放行规则的源改为“除 Kindle IPv4/IPv6 地址以外的设备”，目标和端口保持原样，原 SSH 策略保留。策略加入 Kindle 无法访问 NAS 管理、共享文件及 HA 原端口的断言，以及电脑 IPv4/IPv6 原权限保留的断言。

当前 IP set 不接受 `*` 或 `/0` 成员，使用覆盖所有可用源地址的 IPv4/IPv6 范围，再移除 Kindle 两个地址。不要只枚举当前在线设备，否则会改变其他设备和后续入网设备的权限。

隔离适用于 Tailscale 远程路径。普通局域网和 NAS 的其他公网入口仍由各自网络及应用认证保护；只读网关在任何路径上都执行白名单和方法限制。

## 验证与维护

`tests/test_home_readonly.py` 覆盖真实 HTTP 请求的鉴权、越权指标、写入方法、路径穿越、过期导出和属性裁剪。`scripts/probe-home-access.go` 在 Kindle 上通过实际 Tailscale 连接测试指定 NAS 端口及网关拒绝行为，不输出令牌，不调用真实设备控制服务。

本次记录：`build/mihome-readonly-validation.json`、`build/mihome-readonly-migration.json`、`build/home-permissions-before.json`、`build/home-permissions-after.json`。原策略和已发布策略分别保留在 `build/tailnet-policy-before.hujson` 与 `build/tailnet-policy-readonly.json`；HA 原配置备份在 NAS `/config/.paperos-readonly-backup/`。

`scripts/secure-mihome.py` 是旧版直连设备的一次性迁移工具：本机进程暂存受限令牌，NAS 安装文件只含摘要和白名单，通过固定主机密钥的 SSH 写入 Kindle，验证新读数后撤销旧 HA 会话。成功后关闭临时进程。已隔离的设备不应重新运行旧 `connect-mihome.py` 向导；原 HA 令牌已撤销，恢复旧配置文件不会恢复访问。
