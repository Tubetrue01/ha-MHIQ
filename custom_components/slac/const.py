DOMAIN = "slac"
PLATFORM_NAME = "三菱智能空调"

CONF_IDENTITY_ID = "identity_id"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_IOT_TOKEN = "iot_token"
CONF_PHONE = "phone"
CONF_PASSWORD = "password"
CONF_PROVINCE = "province"
CONF_CITY = "city"
CONF_SUB_LOCALITY = "sub_locality"
CONF_ENABLE_WEATHER = "enable_weather"

DEVICE_TYPE_AC = 0

# ---- WorkMode 映射 (来自 APK DeviceStatusInfo_AC) ----
AC_MODE_HA_MAP = {
    0: "auto",
    1: "cool",
    2: "heat",
    3: "fan_only",
    4: "dry",
}
HA_MODE_TO_AC = {v: k for k, v in AC_MODE_HA_MAP.items()}

# ---- WindSpeed 映射 ----
FAN_MODE_MAP = {
    "自动": 0,
    "静音": 1,
    "超低": 2,
    "低风": 3,
    "中风": 4,
    "高风": 5,
    "超高": 6,
}

FAN_MODE_LIST = list(FAN_MODE_MAP.keys())
FAN_MODE_TO_AC = {k: v for k, v in FAN_MODE_MAP.items()}
AC_TO_FAN_MODE = {v: k for k, v in FAN_MODE_MAP.items()}

# ---- Horizontal 摆叶映射 ----
SWING_MODE_MAP = {
    "自动": 0,
    "位置1": 1,
    "位置2": 2,
    "位置3": 3,
    "位置4": 4,
}

SWING_MODE_LIST = list(SWING_MODE_MAP.keys())
SWING_MODE_TO_AC = {k: v for k, v in SWING_MODE_MAP.items()}
AC_TO_SWING_MODE = {v: k for k, v in SWING_MODE_MAP.items()}

# ---- CleaningDegerming 映射 (单属性三功能) ----
# 0=关闭, 1=自清洁, 2=热除菌, 3=舒适风
PRESET_MODE_MAP = {
    "自清洁": 1,
    "热除菌": 2,
    "舒适风": 3,
}
PRESET_MODE_LIST = list(PRESET_MODE_MAP.keys())
AC_TO_PRESET_MODE = {v: k for k, v in PRESET_MODE_MAP.items()}

# ---- HVAC 动作映射 ----
# 当 WorkMode 运行时对应的 HVACAction
# auto 模式不确定实际动作,返回 IDLE
HVAC_ACTION_MAP = {
    1: "cooling",
    2: "heating",
    3: "fan",
    4: "drying",
}

COORDINATOR_UPDATE_INTERVAL = 10

# Token 刷新策略：token 有效期20h（服务器返回 iotTokenExpire=72000s），
# 当剩余时间 < 1h 时触发刷新，确保永不过期且预留充足重试时间
# ⚠️ 20h 有效期未经长时间验证，如遇 token 过期报错，可适当调大此值
TOKEN_REFRESH_INTERVAL = 1 * 3600  # 提前1小时刷新（即19小时刷新）

# ---- MQTT 配置 ----
# 来自逆向分析（MqttConfigure.java, b.java）
# Broker: public.iot-as-mqtt.cn-shanghai.aliyuncs.com:1883
CONF_MQTT_ENABLED = "mqtt_enabled"
CONF_MQTT_PRODUCT_KEY = "mqtt_product_key"
CONF_MQTT_DEVICE_NAME = "mqtt_device_name"
CONF_MQTT_DEVICE_SECRET = "mqtt_device_secret"

# MQTT 连接参数（与 MqttConfigure.java 一致）
MQTT_CONNECT_TIMEOUT = 10  # 10 秒连接超时（setConnectionTimeout(10)）
MQTT_KEEPALIVE = 65       # 与 App 一致的 KeepAlive 间隔（65s）
MQTT_SECURE_MODE = 2      # 2=TLS (默认), 3=TCP（来自 MqttConfigure.SECURE_MODE）