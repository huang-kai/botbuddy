# BotBuddy / BotSkills 更名与迁移


1.3.0 起，框架名为 **BotBuddy**，技能集合名为 **BotSkills**。这是第三方项目，原厂 SDK、接口和设备标识不随项目改名。

已有安装首次迁移请使用**完整新安装包**，在原安装板退出语音会话后执行：

```bash
unzip botbuddy-1.3.0.rpk -d ./botbuddy-release
cd botbuddy-release
source ./scripts/install.sh --no-onboard
botbuddy --version
botbuddy skill list
```

新安装器会在 `~/.primebuddy` 原地更新；不复制或搬动配置、技能、QQ 登录态、设备身份及运行恢复记录。全新安装使用 `~/.botbuddy`。曾使用自定义目录时，继续传入 `--home /原安装目录`；旧 `PRIMEBUDDY_HOME` 也有效。新旧默认目录同时存在时必须显式指定，安装器不会合并或猜测。双板自动安装会在目标板解析默认路径。

- `botbuddy` 是新命令，安装器同时提供 `primebuddy` 兼容入口，两者绑定同一安装目录和锁。shell 中旧的托管 PATH 块会替换为新块，保留其他设置。
- 环境变量统一为 `BOTBUDDY_HOME`、`BOTBUDDY_RUNTIME`、`BOTBUDDY_LOG_DIR`；旧 `PRIMEBUDDY_*` 仍兼容，新变量优先。技能子进程同时收到新旧 HOME、SKILL_DATA、SKILL_CONFIG 变量。
- 新技能使用 `cfg/pkg.yaml` 的 `botbuddy` 键；旧 `primebuddy` 键及 Python 导入仍有效。两份键内容冲突时拒绝加载。
- 现有 SSH 私钥、授权和日志目录配置继续保留。`--sdk-bridge namespaced` 保留原 `/primebuddy` 通信地址；新客户端可用 `--sdk-bridge botbuddy` 选择 `/botbuddy`。
- 有未完成升级或运行恢复记录时先恢复，不能删除记录跳过检查。中断后 `botbuddy update --recover` 和 `primebuddy update --recover` 均可使用。

旧版在线更新器只认识 `primebuddy-*.rpk`，因此 **1.0.x / 1.1.x / 1.2.x → 1.3.0 的首次更名使用上述安装脚本**。后续再用 `botbuddy update`。不要把旧包简单改名冒充新包。

新代码位于 [huang-kai/botbuddy](https://github.com/huang-kai/botbuddy)。旧 [huang-kai/primebuddy](https://github.com/huang-kai/primebuddy) 保留历史代码、Issues 和 Release，停止维护，并在首页引导至新项目；这是新建仓库，不会产生 GitHub 地址重定向。BotBuddy 的后续在线更新仅查询新仓库。技能库远程仍为 `huang-kai/primeskills`，本地目录为 `BotSkills`。代码发布不等于已发布新 Release，安装包以新仓库实际 Release 为准。


此次更名基于上游 PrimeBuddy 1.2.1。保留上游纯平台包、随包技能选择和兼容技能独立升级语义；完整包默认附带点歌台和成语接龙，易来仍单独安装。

如已有不兼容的旧易来（例如 0.2.0），离线安装前需将独立 `yeelight-0.3.2.rpk` 放入解压目录的 `resource/bundled/`，供安装器准备升级；仍兼容的已安装技能原样保留。不要仅因推荐版本变更而重置配置或登录。
