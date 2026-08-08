# MHIQ — Mitsubishi Smart AC

[![HACS Validation](https://img.shields.io/badge/HACS-Custom-orange)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1-blue)](https://www.home-assistant.io)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-C3H3--AI-blue)](https://github.com/C3H3-AI/ha-MHIQ)

Home Assistant custom integration for **Mitsubishi Heavy Industries Haier (三菱重工海尔)** smart air conditioners using the **SC-MIAS-W3M** WiFi module.

> **Model**: SC-MIAS-W3M (三菱重工海尔 WiFi module)
> **Brand**: MHIQ — Mitsubishi Heavy Industries Haier (三菱重工海尔)
> **App**: SLAC (三菱智能空调)
> **Connection**: Cloud Polling (API)

---

## Features

- Control up to **9 air conditioner units** (8 indoor + 1 floor heating module) through a single WiFi module
- Full climate control: mode (cool/heat/fan/dry/auto), temperature, fan speed, swing, preset
- **Floor heating** support (addr=0): power on/off, temperature control
- **Preset modes**: 自清洁 / 热除菌 / 舒适风
- **Horizontal swing**: 自动 / 位置1-4
- Real-time temperature readings for each indoor unit
- Individual entities for **fresh air** and **auxiliary electricity** control per unit
- **Water pump** status monitoring per unit
- **Error code** and **control mode** sensors per unit
- Built-in **weather service** (optional): outdoor temperature, humidity, wind, air quality, PM2.5
- Config Flow setup via **phone number + password** login
- Supports **Chinese mainland phone numbers**
- Auto token refresh (19h cycle, refresh when <1h remaining)
- Auto re-login on token expiry
- Pure Python RSA encryption (no external crypto dependency)
- Options Flow to toggle weather service on/off without reinstall

> **Note**: MQTT push channel is currently sealed (connection instability with RC=128). API polling at 10s interval is used instead. MQTT code is preserved in codebase for future restoration.

---

## Hardware

| Component | Description |
|-----------|-------------|
| **WiFi Module** | SC-MIAS-W3M, manufactured by Mitsubishi Heavy Industries Haier |
| **Communication** | Cloud-based (WiFi module connects to manufacturer's IoT cloud) |
| **Units** | Up to 9 indoor units per module (including floor heating) |
| **Network** | Standard 2.4GHz WiFi |

---

## Installation

### HACS (Custom Repository)

1. Open HACS → Integrations → Custom repositories
2. Add this repository URL: `https://github.com/C3H3-AI/ha-MHIQ`
3. Category: **Integration**
4. Click **Download**
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/slac/` directory to your HA `config/custom_components/` directory
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration
4. Search for "Mitsubishi Smart AC" or "SLAC"

---

## Configuration

### Step 1: Phone Login

1. Enter your Chinese mainland phone number
2. Enter your SLAC app password
3. Enable "Weather service" if desired (requires location)
4. Click Submit

### Step 2: Location (Weather Only)

If you enabled weather service and left location fields empty, the integration will attempt to auto-detect your location based on your Home Assistant public IP. If detection fails, weather is silently disabled.

Alternatively, manually enter:

| Field | Description | Example |
|-------|-------------|---------|
| Province | Province name | Jiangsu |
| City | City name | Nanjing |
| District | District/county | Gulou |

### Post-Install Options

After installation, go to **Configure** to:

| Option | Description |
|--------|-------------|
| Toggle weather | Enable/disable weather sensors |
| Update location | Change province/city/district |
| Re-login | Update phone/password |

---

## Entities

### Climate (per unit)

Each unit identified by its internal address (0-8).

| Entity ID Pattern | Description |
|-------------------|-------------|
| `climate.slac_ac_0` | Floor heating module |
| `climate.slac_ac_1` ~ `climate.slac_ac_8` | Indoor units |

**Supported HVAC Modes** (indoor): off, cool, heat, fan_only, dry, auto
**Supported HVAC Modes** (floor): off, heat

**Features** (indoor only): fan mode, swing mode, preset mode (自清洁/热除菌/舒适风)

### Sensor (per unit)

| Entity ID Pattern | Description | Unit |
|-------------------|-------------|------|
| `sensor.slac_error_{addr}` | Error code | - |
| `sensor.slac_control_mode_{addr}` | Control mode (local/remote) | - |
| `sensor.slac_type_code_{addr}` | Device type code (indoor only) | - |

### Sensor (Weather - Optional)

Enabled only if weather service is toggled on.

| Entity ID Pattern | Description | Unit |
|-------------------|-------------|------|
| `sensor.slac_weather_location` | Weather location | - |
| `sensor.slac_weather_outdoor_temp` | Outdoor temperature | °C |
| `sensor.slac_weather_cond` | Weather condition | - |
| `sensor.slac_weather_air_quality` | Air quality | - |
| `sensor.slac_weather_pm25` | PM2.5 | µg/m³ |
| `sensor.slac_weather_temp_max` | Max temperature | °C |
| `sensor.slac_weather_temp_min` | Min temperature | °C |
| `sensor.slac_weather_comfort` | Comfort level | - |
| `sensor.slac_weather_wind` | Wind level | - |

### Switch (per indoor unit, addr 1-8)

| Entity ID Pattern | Description |
|-------------------|-------------|
| `switch.slac_fresh_air_{addr}` | Fresh air control |
| `switch.slac_auxiliary_electricity_{addr}` | Auxiliary electricity (heat) control |

### Binary Sensor

| Entity ID Pattern | Description |
|-------------------|-------------|
| `binary_sensor.slac_online_module` | WiFi module online status |
| `binary_sensor.slac_online_{addr}` | Sub-device online status (all units) |
| `binary_sensor.slac_water_pump_{addr}` | Water pump running status (indoor only) |

### Entity Count Summary

| Platform | Count | Weather Disabled |
|----------|-------|------------------|
| climate | 9 | 9 |
| sensor | 26 + 10 weather = 36 | 26 |
| switch | 16 | 16 |
| binary_sensor | 18 | 18 |
| **Total** | **79** | **69** |

---

## Architecture

### Polling Model

The integration uses **cloud polling** at 10-second intervals. Each poll:

1. Checks token expiry (refresh if <1h remaining)
2. Fetches device list (single API call for all units)
3. Fetches all device properties in a **single API call** (all 9 units share the same `iotId`)
4. Optionally fetches weather data

### Token Lifecycle

1. **Login**: Phone + password → RSA encrypted → OA auth → get `identityId` + `refreshToken` + `iotToken`
2. **Refresh**: When `iotToken` has <1h remaining (≈19h after issuance), auto-refresh via `createSessionByAuthCode`
3. **Re-login**: If both token and refresh fail, auto re-login with stored credentials

### Dependencies

- `aiohttp` (async HTTP, built-in with HA)
- Pure Python RSA encryption (no `cryptography` library required)
- `paho-mqtt` (kept as optional, MQTT currently sealed)

---

## Credits

- **Author**: [C3H3-AI](https://github.com/C3H3-AI)
- **Reverse Engineering**: Frida + apktool + MuMu emulator

---

## Changelog

### v1.2.0 (2026-08-08)

- ✅ Switched to cloud polling (10s interval), MQTT sealed due to connection instability
- ✅ Removed `cryptography` dependency, pure Python RSA implementation
- ✅ Optimized property fetch: single API call for all 9 units
- ✅ Token refresh: 19h cycle (refresh when <1h remaining)
- ✅ Added floor heating support (addr=0)
- ✅ Added preset modes: 自清洁 / 热除菌 / 舒适风
- ✅ Added horizontal swing control
- ✅ Water pump status as binary sensor
- ✅ Fresh air / auxiliary electricity as independent switches
- ✅ Auto re-login on token expiry
- ✅ Entity IDs stabilized with consistent naming

### v1.1.0 (2026-07-28)

- ✅ Initial stable release
- ✅ Climate control: temperature, mode, fan speed
- ✅ Phone + password login
- ✅ Weather service (optional)
- ✅ Config flow + options flow

---

## License

MIT License

---

## Disclaimer

This integration is an independent, community-developed project. It is not affiliated with, endorsed by, or officially supported by Mitsubishi Heavy Industries Haier or any of its subsidiaries. Use at your own risk.
