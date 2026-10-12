# aTrust Fedora native update repository

这是个人维护的、非官方的深信服 aTrust Fedora 原生适配和签名 DNF 更新仓库。
当前目标为 Fedora 44 x86_64。首个适配来源为官方 Ubuntu 客户端 2.5.16.50。
目前发布包使用本机已有的 `stonesun` 用户组；其他机器请审阅并调整 `config.json` 后自行构建。

## 接入 DNF

完成仓库首次发布后：

```bash
curl -fLO https://stonehfzs.github.io/atrust-fedora/atrust-fedora.repo
sudo install -m 0644 atrust-fedora.repo /etc/yum.repos.d/atrust-fedora.repo
sudo dnf upgrade --refresh cn.com.sangfor.atrust
```

仓库开启 RPM 签名和仓库元数据签名验证。首次导入密钥时，应将 DNF 显示的指纹与本仓库
`RPM-GPG-KEY-atrust-fedora` 的指纹核对。支持的系统范围以仓库路径为准；没有 Fedora 其他版本的包时不会提供对应更新。

本仓库签名公钥指纹：`465DA2EFBC9EB7525965CA13AE4371CA81B1E124`。

### GitHub 下载需要代理时

普通命令可以下载、`sudo dnf` 却超时时，请检查系统权限下的代理配置。
终端中的 `http_proxy`、`https_proxy` 属于当前进程的环境，提权工具可能会清理它们。
DNF 在没有自己的代理配置、也没有代理环境变量时会尝试直连。
在 Fedora 44 的 DNF5 中，建议用原生配置管理命令保存已有代理，例如：

```bash
sudo dnf config-manager setopt atrust-fedora.proxy=http://127.0.0.1:7890
```

该命令将本机设置写入 `/etc/dnf/repos.override.d/99-config_manager.repo`，
不依赖终端变量，也不会因重新下载或替换 `atrust-fedora.repo` 而丢失。
这只影响 aTrust 仓库；更新时该代理须处于运行状态。无需代理的网络不用添加该项。
代理端口改变时重新运行上面的命令；移除本机覆盖配置可用：

```bash
sudo dnf config-manager unsetopt atrust-fedora.proxy
```

配置行为见 [DNF5 配置说明](https://dnf5.readthedocs.io/en/latest/dnf5.conf.5.html#proxy)
和 [config-manager 官方文档](https://dnf5.readthedocs.io/en/latest/dnf5_plugins/config-manager.8.html)。

## 自动更新如何运行

GitHub Actions 每 6 小时检查一次深信服官方 CDN 索引，也可在 Actions 页面手动运行。
检查时间可能因 GitHub 排队而延迟。每月向 `.checks/upstream.json` 提交一次官方索引检查记录，
提供审计信息，并保持仓库活动，避免公开仓库因 60 天无活动而被 GitHub 自动停用定时任务。
该 GitHub 行为见[官方说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。
在 Actions 页面查看最近运行结果；失败时仍保留已发布的包。检查记录只证明读到了索引，不代表新版已经发布。

1. 只接受官方 HTTPS Ubuntu amd64 下载地址，不执行下载的索引 JavaScript。
2. 原始包记录 SHA256；已知基线的哈希必须匹配。哈希记录用于完整性和追溯，不代表厂商独立签名。
3. 检查 DEB 包名、版本、架构、归档路径和链接，再提取到全新的临时目录。
4. 应用已经验证的适配。补丁位置、ABI 或文件布局变化时构建失败，保持已发布版本。
5. 检查 JavaScript 和 Shell 语法、浏览器 URL 和环境回归、核心动态库、RPM 完整性及安装依赖。
6. 使用仓库独立 OpenPGP 密钥签名 RPM，再验证签名。
7. 发布 GitHub Release，生成并签名 `repomd.xml`，部署 GitHub Pages 上的 DNF 索引。

自动检查通过不代表真实机构内网资源已验收。SSH、RDP、内网 DNS、UEM 和终端合规策略需在授权环境里验证。

## 首次发布配置

仓库需要 GitHub Pages 的发布来源设置为 GitHub Actions，以及：

- Actions secret `RPM_SIGNING_PRIVATE_KEY_B64`：专用仓库签名私钥的 Base64 内容。
- Actions variable `RPM_SIGNING_KEY_ID`：完整 OpenPGP 指纹。
- 仓库中提交 `RPM-GPG-KEY-atrust-fedora` 公钥，私钥不得提交。

首次配置可在本机 GitHub CLI 登录完成后运行：

```bash
python3 scripts/setup_github.py --key-home /path/to/dedicated/gnupg \
  --key-id 465DA2EFBC9EB7525965CA13AE4371CA81B1E124
```

此命令会创建配置中的公开仓库、上传专用签名私钥到 GitHub Actions 加密 Secret、推送源码、启用 Pages，并触发首次发布。

适配逻辑修改后递增 `config.json` 的 `packaging_revision`。上游版本自动从官方索引读取。
已经公开的 Release 保持不变；修复通过新的 RPM release 编号发布。

## 本机构建

```bash
python3 scripts/build.py check
python3 scripts/build.py build
```

离线构建使用之前下载的目录：

```bash
python3 scripts/build.py build --offline --work /path/to/cache \
  --version 2.5.16.50 --deb /path/to/aTrustInstaller_amd64.deb
```

新版本本地 DEB 必须通过 `--sha256` 指明已核实的校验值。
需要 Fedora 44 构建环境、Python、Node.js、curl、dpkg-deb、rpmbuild 及运行库。

## 备份和回退

仓库包升级前会停止后台并把运行状态归档到 `/var/lib/atrust-fedora-backups`，目录只允许 root 访问。
升级后恢复原来的后台运行状态，桌面窗口应重新打开。备份失败时阻止升级。

```bash
sudo dnf downgrade cn.com.sangfor.atrust
```

发布索引保留当前及最近两个版本供回退。旧运行数据的恢复应在停止客户端后进行；当前账号登录状态、网关策略和
数据格式可能影响跨版本恢复，备份文件不可公开上传。

## 代码和上游许可

本仓库的适配脚本使用 MIT 许可。深信服客户端及其依赖保留各自原有版权和许可；脚本许可不重新授权上游二进制。
本仓库不包含账号、私有签名密钥、机构登录凭据或会话备份。
