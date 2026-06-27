# MagicPush Bridge Integration

将 [MagicPush](https://github.com/sss/magicpush)（自托管多通道消息推送网关）的接口管理中的推送接口映射为 Home Assistant 的服务动作，让 HA 自动化可以直接调用 MagicPush 的消息推送能力。

## 功能描述

MagicPush Bridge 是一个 Home Assistant 自定义组件（Custom Component），作为 HA 与 MagicPush 之间的桥接层：

- **接口映射**：登录 MagicPush 服务后，自动获取该服务中已配置的推送接口（Endpoints），每个接口成为一个可在 HA 中调用的服务目标
- **多实例支持**：可添加多个 MagicPush 服务实例（不同的服务器或不同的管理员账号）
- **实时同步**：通过 `update_endpoints` 服务刷新端点列表
- **消息推送**：支持 `text`、`markdown`、`html` 三种消息格式，以及可选的点击跳转 URL

### 工作原理

```
HA Automation  →  magicpush.send_message  →  MagicPush /api/push  →  Channels (Telegram, Bark, WeCom...)
```

HA 通过服务调用将消息发送到 MagicPush，MagicPush 根据端点绑定的渠道列表分发消息。

---

## 安装

### 通过 HACS 安装（推荐）

1. 确保已安装 [HACS](https://hacs.xyz/)
2. 在 HACS 中添加自定义仓库：
   - URL: `https://github.com/sss/magicpush-bridge-integration`
   - Category: `Integration`
3. 搜索并安装 `MagicPush Bridge`
4. 重启 Home Assistant

### 手动安装

1. 在 HA 配置目录下创建 `custom_components/magicpush/` 目录
2. 将本仓库中的 `custom_components/magicpush/` 全部文件复制到上述目录
3. 重启 Home Assistant

---

## 配置

### 添加集成

1. 进入 Home Assistant → **设置** → **设备与服务** → **添加集成**
2. 搜索 **MagicPush Bridge**
3. 填写以下信息：
   - **Server URL**：MagicPush 服务地址，例如 `http://192.168.1.100:3000`
   - **Username / Email**：MagicPush 管理员登录邮箱
   - **Password**：MagicPush 管理员密码
4. 点击提交，系统将验证连接并拉取端点列表

### 添加多个实例

重复上述步骤即可添加多个 MagicPush 服务实例，每个实例独立管理其端点。

---

## 使用

### 服务：`magicpush.send_message`

通过指定端点发送消息。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `endpoint` | string | 是 | 端点名称（MagicPush 接口管理中的接口名称） |
| `content` | string | 是 | 消息正文 |
| `title` | string | 否 | 消息标题 |
| `type` | select | 否 | 消息格式：`text`（默认）、`markdown`、`html` |
| `url` | string | 否 | 点击跳转链接（部分渠道支持） |

#### YAML 示例

```yaml
action:
  service: magicpush.send_message
  data:
    endpoint: "My Endpoint"
    title: "Home Alert"
    content: "Motion detected at front door"
    type: text
```

#### 通过 UI 自动化

在自动化编辑器中，选择动作类型为 **Call service**，服务选择 **MagicPush Bridge: Send message**，然后填写字段。

### 服务：`magicpush.update_endpoints`

刷新当前所有已配置实例的端点列表（当 MagicPush 服务中的接口发生变化时调用）。

无参数。

---

## 开发

### 项目结构

```
custom_components/magicpush/
├── __init__.py          # 组件入口：async_setup_entry / async_unload_entry，注册 HA 服务
├── config_flow.py       # 配置流程：UI 表单，连接验证，错误处理
├── const.py             # 常量定义：DOMAIN, 配置键, 服务名, 属性名
├── hub.py               # 通信层：MagicPush API 包装器，包含登录/刷新令牌/获取端点/推送
├── services.yaml        # HA 服务定义元数据（用于 UI 渲染）
├── strings.json         # 开发期翻译文件
├── manifest.json        # 组件清单：域名, 版本, iot_class, 依赖
└── translations/
    └── en.json          # 运行时英文翻译
```

### 核心模块说明

#### hub.py — MagicPush API 通信层

`MagicPushHub` 类封装了与 MagicPush 服务的 HTTP 通信：

- **认证流程**：`/api/auth/login` → 获取 JWT accessToken / refreshToken，通过 Axios 风格的自动刷新机制（在 HTTP 401 时自动调用 `/api/auth/refresh`）
- **端点获取**：`GET /api/endpoints` 拉取所有推送接口（分页参数 pageSize=1000 获取全部）
- **消息推送**：`POST /api/push` 通过端点令牌（Bearer Token）发送消息
- **超时控制**：所有请求默认 15 秒超时

#### config_flow.py — 配置流程

基于 `ConfigFlow` 实现：

- `async_step_user`：三步校验（URL 格式 → 登录验证 → 端点拉取）
- 错误处理：`CannotConnect`（连接超时/网络错误）、`InvalidAuth`（用户名密码错误）

#### __init__.py — 服务注册

- `async_setup_entry`：每个配置条目创建独立的 `MagicPushHub` 实例，存储在 `entry.runtime_data` 中；注册 `send_message` 和 `update_endpoints` 服务（仅首次注册）
- `async_unload_entry`：清理 HTTP 会话，最后一个条目卸载时移除服务
- `_find_endpoint`：在所有配置实例中按名称查找端点，支持多实例场景

### API 参考

| HA 服务 | 对应 MagicPush API | 方法 |
|---------|--------------------|------|
| `magicpush.send_message` | `POST /api/push` | Bearer Token (endpoint token) |
| `magicpush.update_endpoints` | `GET /api/endpoints` | JWT Bearer Token |

MagicPush 完整的 API 文档见 `docs/magicpush/docs/开发文档/README.md`。

### 扩展建议

- **添加实体支持**：可为每个端点创建 `sensor` 实体展示状态（在线/离线），或创建 `button` 实体快速推送测试消息
- **推送日志**：通过 `GET /api/logs` 在 HA 中展示推送历史
- **渠道管理**：通过 `GET /api/channels` 在 HA 中浏览和管理消息渠道
- **诊断面板**：实现 `diagnostics.py` 提供配置诊断信息

---

## 许可证

MIT
