# 部署到腾讯云轻量应用服务器（Lighthouse）

> 配置：国内节点 / 无域名 / 用公网 IP 访问 / 公开访问 / root + 123123 / 预算 ¥100 月

---

## ⚠️ 关于端口的重要说明

国内节点 **没有 ICP 备案的域名时，腾讯云会拦截 80 / 443 端口**，访问会跳到「备案提示」页。
所以本方案统一走 **8000 端口**，访问地址为 `http://公网IP:8000`。如果以后申请到备案域名，再切到 80/443 + 反向代理 + HTTPS。

---

## 一、购买轻量应用服务器（约 5 分钟）

控制台地址：<https://console.cloud.tencent.com/lighthouse>

| 选项 | 推荐值 |
|---|---|
| 地域 | **上海** 或 **广州**（任选其一即可） |
| 镜像 | **应用镜像** → 选 `Docker CE`（Ubuntu 22.04 + Docker 已装好） |
| 套餐 | **2 核 4 GB · 6 Mbps · 80 GB SSD**（约 ¥75/月，预算内） |
| 时长 | 1 个月起，到期自动续费可关 |
| 登录方式 | 设管理员密码（也可后续上传 SSH 密钥） |

下单后等待 1–2 分钟，实例状态变成「运行中」即可。
**记下控制台显示的「公网 IP」**（下文记为 `<IP>`）。

> 1c2g 套餐（约 ¥30/月）也够跑，只是构建镜像时稍慢。

---

## 二、放行 8000 端口

控制台 → 点进刚买的实例 → 左侧 **防火墙** → **添加规则**：

| 字段 | 值 |
|---|---|
| 应用类型 | 自定义 |
| 协议 | TCP |
| 端口 | `8000` |
| 来源 | `0.0.0.0/0`（公开访问）|
| 策略 | 允许 |
| 备注 | `Boyuan Internal Tools` |

---

## 三、把代码上传到服务器

**在你本地 Mac 终端**（注意当前目录是 `/Users/lyy/work`，**外面**那一层）：

```bash
cd /Users/lyy/work
tar --exclude='boyuan/.venv' \
    --exclude='boyuan/__pycache__' \
    --exclude='boyuan/.DS_Store' \
    --exclude='boyuan/.git' \
    --exclude='boyuan/.claude' \
    --exclude='boyuan/.env' \
    --exclude='boyuan/samples/*.xls' \
    --exclude='boyuan/samples/*.xlsx' \
    -czf boyuan.tgz boyuan/

scp boyuan.tgz root@<IP>:/root/
```

（首次连接会提示 `Are you sure you want to continue connecting?` 输入 `yes`，然后输入服务器密码。）

---

## 四、登录服务器并启动

```bash
ssh root@<IP>
```

进入服务器后：

```bash
# 1. 解压代码
cd /root
tar -xzf boyuan.tgz
cd boyuan

# 2. 生成 session 密钥并写入 .env
SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
echo "BOYUAN_SESSION_SECRET=$SECRET" > .env

# 3. 构建并启动（首次约 1–2 分钟）
docker compose up -d --build

# 4. 看日志确认启动成功
docker compose logs -f
```

看到 `Uvicorn running on http://0.0.0.0:8000` 就成功了。`Ctrl+C` 退出日志查看（不会停容器）。

---

## 五、访问

浏览器打开：

```
http://<IP>:8000
```

账号 `root@boyuanpharm.com`，密码 `123123`。

---

## 六、日常运维

```bash
# 查看运行状态
docker compose ps

# 查看实时日志
docker compose logs -f

# 重启
docker compose restart

# 停止
docker compose down

# 完全删除容器（保留镜像）
docker compose down --remove-orphans
```

### 更新代码（改了之后重新部署）

**本地：**
```bash
cd /Users/lyy/work
tar --exclude='boyuan/.venv' --exclude='boyuan/__pycache__' \
    --exclude='boyuan/.DS_Store' --exclude='boyuan/.git' \
    --exclude='boyuan/.claude' --exclude='boyuan/.env' \
    --exclude='boyuan/samples/*.xls' --exclude='boyuan/samples/*.xlsx' \
    -czf boyuan.tgz boyuan/
scp boyuan.tgz root@<IP>:/root/
```

**服务器：**
```bash
cd /root
tar -xzf boyuan.tgz   # 覆盖式解压
cd boyuan
docker compose up -d --build
```

固定资产台账数据现在存储在 MySQL 表中，不再依赖本地 JSON 数据文件。

---

## 七、安全建议（部署后逐步落实）

1. **改 SSH 端口**：把默认 22 端口改掉，加防火墙规则；减少暴力破解。
2. **改 root 密码或禁 root 登录**：用普通用户 + sudo。
3. **改初始管理员密码**：首次启动会创建 `root@boyuanpharm.com` / `123123`。登录后请通过邀请流程创建新的管理员账号，确认可登录后停用或替换初始账号。
4. **(后续) 申请备案域名 + HTTPS**：拿到备案号后，把腾讯云 SSL 证书装上，加 nginx 做 80/443 反代。

---

## 八、常见问题

**Q: 浏览器访问 `http://<IP>:8000` 一直转圈不出页面？**
A: 99% 是防火墙没放行。回到第二步检查「8000 端口规则」是否真的「允许」。

**Q: `docker compose up` 报 `command not found: docker`？**
A: 你买实例时没选 Docker 应用镜像。手动安装：
```bash
curl -fsSL https://get.docker.com | bash
systemctl enable --now docker
```

**Q: 报 `docker compose` 命令不存在，但有 `docker-compose`？**
A: 这是 Compose v1。把命令里的 `docker compose` 全部改成 `docker-compose` 即可。

**Q: 重启服务器后应用没起来？**
A: docker-compose.yml 里写了 `restart: unless-stopped`，正常会自启。如果没起，运行 `cd /root/boyuan && docker compose up -d`。

**Q: 上传 Excel 时浏览器报「连接被重置」？**
A: 检查防火墙 8000 端口；查看容器日志 `docker compose logs --tail 100`。
