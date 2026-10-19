# 发布 PaperOS 源码和应用

公开项目：[PaperOS](https://github.com/ChrisPei/PaperOS)；应用目录：[paperos-apps](https://github.com/ChrisPei/paperos-apps)。

开发目录同时保存私有设备备份、凭据和存档，不能整体提交。使用
`python3 scripts/prepare-public-source.py --output build/publish/source-review-<版本>`
导出新的源码审核目录；脚本使用允许目录，排除设备产物，并检查私钥和令牌标记。
审核通过后再把差异同步到公开仓库工作副本。仓库工作副本与设备开发目录分别管理。

应用包由 `scripts/build-app-catalog.py` 生成。签名私钥留在维护者电脑，例如
`~/.local/share/paperos/catalog-signing-key.pem`，权限 0600；公钥可公开。
发布前先构建应用、运行测试，更新版本号，保留对应源码及第三方许可证。
已经发布的同版本包不覆盖；改动代码后发布新的版本。

目前小应用包放在应用仓库的 `packages/`；客户端使用 GitHub 官方 Contents API 的 raw
媒体类型，避免部分网络无法访问 Release 跳转入口。大型对应源码包放在 Releases。
GitHub 匿名 API 有请求限额；触发限额或网络失败时可继续使用已安装应用和缓存目录，稍后重试。
不能通过关闭 TLS 校验或跳过目录签名来处理网络失败。

先上传新版本包，确认 URL 和 SHA-256，再提交 `catalog.json`、`catalog.json.sig`。
`testing/` 是独立 SDK 验证源，不进入默认目录。测试包也需要在 Kindle 本机确认安装。

仅源码公开，没有通用刷机镜像。当前显示、触控、休眠和启动适配验证针对 KT3。
原厂固件、个人备份、商业游戏、私钥、家庭中枢凭据与用户数据均不发布。
