# 三菱智能空调 Home Assistant 集成

[![HACS Validation](https://img.shields.io/badge/HACS-Custom-orange)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1-blue)](https://www.home-assistant.io)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

通过本集成，您可以在 Home Assistant 中控制 **三菱重工海尔** 智能空调。

## 硬件支持

本集成适用于使用 **SC-MIAS-W3M** WiFi 模块的空调设备：

- 品牌：三菱重工海尔
- 配套 APP：三菱智能空调 (SLAC)
- 每个 WiFi 模块支持最多 **9 台室内机**（含地暖模块）

## 功能特性

- 控制所有室内机：开关、温度、模式、风速、摆叶
- 支持模式：制冷 / 制热 / 除湿 / 送风 / 自动
- 地暖模块支持（addr=0）
- 预设模式：自清洁 / 热除菌 / 舒适风
- 新风控制、辅热控制（独立开关实体）
- 水泵状态监测
- 故障码、控制模式传感器
- 可选天气服务（室外温度、空气质量等）
- Token 自动刷新，无需担心过期
- 手机号 + 密码登录，开箱即用

## 安装

### 方式一：HACS 安装（推荐）

1. 打开 **HACS → 集成 → 自定义仓库**
2. 添加仓库地址：`https://github.com/C3H3-AI/ha-MHIQ`
3. 类别选择：**集成**
4. 点击 **下载**
5. 重启 Home Assistant

### 方式二：手动安装

1. 将 `custom_components/slac/` 目录复制到 HA 的 `config/custom_components/` 目录
2. 重启 Home Assistant
3. 进入 **设置 → 设备与服务 → 添加集成**
4. 搜索 "三菱智能空调" 或 "SLAC"

## 配置

1. 输入您的**中国大陆手机号**
2. 输入您的**三菱智能空调 APP 密码**
3. 如需天气服务，可开启并填写所在地区
4. 点击提交完成配置

## 实体说明

### 空调 (Climate)

每台室内机对应一个 climate 实体：

- `climate.slac_ac_0` — 地暖模块
- `climate.slac_ac_1` ~ `climate.slac_ac_8` — 室内机

### 开关 (Switch)

| 实体 | 说明 |
|------|------|
| `switch.slac_fresh_air_{addr}` | 新风开关 |
| `switch.slac_auxiliary_electricity_{addr}` | 辅热开关 |

### 传感器 (Sensor)

| 实体 | 说明 |
|------|------|
| `sensor.slac_error_{addr}` | 故障码 |
| `sensor.slac_control_mode_{addr}` | 控制模式（本地/远程） |
| `sensor.slac_type_code_{addr}` | 设备型号 |
| `sensor.slac_weather_*` | 天气信息（可选） |

### 二值传感器 (Binary Sensor)

| 实体 | 说明 |
|------|------|
| `binary_sensor.slac_online_module` | WiFi 模块在线状态 |
| `binary_sensor.slac_online_{addr}` | 设备在线状态 |
| `binary_sensor.slac_water_pump_{addr}` | 水泵运行状态 |

## 常见问题

**Q: 支持哪些型号的空调？**
A: 使用 SLAC APP 管理的三菱重工海尔空调，搭配 SC-MIAS-W3M WiFi 模块。

**Q: 一个账号可以控制多个 WiFi 模块吗？**
A: 可以。同一个账号下所有设备都会自动发现。

**Q: 为什么需要手机号和密码？**
A: 本集成通过官方 API 与厂商云服务通信，需要您的账号进行认证。密码仅存储在本地，不会上传到任何第三方服务器。

**Q: 实体状态多久更新一次？**
A: 每 10 秒轮询一次。

**Q: 可以不开启天气服务吗？**
A: 可以。天气服务为可选功能，安装时或后续配置中均可关闭。

## 致谢

- 作者：[C3H3-AI](https://github.com/C3H3-AI)

## 许可证

本项目基于 [MIT License](LICENSE) 开源。

## 免责声明

本集成为社区独立开发，与三菱重工海尔及其子公司无任何关联、授权或官方支持。使用本集成所产生的一切后果由使用者自行承担。
