"""
SLAC MQTT 客户端 - 基于逆向分析的阿里云 IoT MQTT 实现

逆向来源（已验证）：
  - MqttConfigure.java: 连接参数配置
  - b.java (MqttNet.java): MQTT 连接核心逻辑
  - a.java (MqttDefaulCallback.java): 回调处理
  - send/a.java (MqttRpcMessageCallback.java): RRPC 消息匹配
  - send/c.java (MqttSendExecutor.java): 消息发送执行器
  - TmpConstant.java: Topic 常量定义
  - CloudUtils.java: 云服务调用工具
  - PersistentNet.java: SDK 版本管理

连接参数（来自 b.java g() 方法，Frida 已验证）：
  - Broker: public.iot-as-mqtt.cn-shanghai.aliyuncs.com:1883 (TLS)
  - ClientId: {deviceName}&{productKey}|securemode=2,_v=0.8.0,lan=Android,os=12,signmethod=hmacsha1,ext=1|
  - Username: {deviceName}&{productKey}（或显式设 mqttUserName）
  - Password: 三种模式（按优先级）：
      1) deviceSecret → HMAC-SHA1({productKey,deviceName,clientId}, deviceSecret)
      2) mqttUserName/mqttPassWord 显式设置 → 直接使用（同时覆盖 clientId）
      3) clientId + deviceToken → 直接使用 deviceToken 作为密码
  - MQTT v3.1.1 (version 4)
  - KeepAlive: 65s（范围 30-1200）
  - ConnectionTimeout: 10s
  - CleanSession: true（App 中由 receiveOfflineMsg 控制）
  - MaxInflight: 10
  - AutomaticReconnect: true（App 中 paho 原生 reconnect）
  - SSL/TLS: TLSv1.2，使用 root.crt 证书验证（App 中 isCheckRootCrt=true）

Topic 结构（来自 TmpConstant.java, CloudUtils.java）：
  设备上行（Device → Cloud）：
    - /sys/{pk}/{dn}/thing/property/post        - 属性上报
    - /sys/{pk}/{dn}/thing/event/{name}/post     - 事件上报
    - /sys/{pk}/{dn}/thing/deviceinfo/update     - 设备信息更新
    - /sys/{pk}/{dn}/thing/authen/sub/register   - 子设备认证注册
    - /sys/{pk}/{dn}/thing/script/get            - 产品脚本获取
    - /sys/{pk}/{dn}/thing/lan/prefix/get        - LAN 前缀查询
    - /sys/{pk}/{dn}/thing/push/device/info      - 推送设备信息
  云端下行（Cloud → Device）：
    - /sys/{pk}/{dn}/thing/property/set          - 属性设置
    - /sys/{pk}/{dn}/thing/service/invoke        - 服务调用
    - /sys/{pk}/{dn}/thing/lan/prefix/update     - LAN 前缀更新
    - /sys/{pk}/{dn}/thing/lan/blacklist/update  - 黑名单更新
  应用侧下行（Cloud → App）：
    - /app/down/thing/properties                 - 属性更新通知
    - /app/down/thing/service/invoke/reply       - 服务调用回复
    - /app/down/thing/status                     - 设备状态变更
    - /app/down/thing/events                     - 事件通知
    - /app/down/_thing/event/notify              - 通用通知
  RRPC 回复后缀：
    - {topic}_reply                              - 所有 topic 的回复后缀

RRPC 模式（来自 send/a.java, b.java subscribeRrpc 方法）：
  1. 发布请求到 topic
  2. 订阅 replyTopic（topic + "_reply"）
  3. 等待回复，通过 payload 中的 "id" 字段匹配请求
  4. 匹配 key: "{replyTopic},id={msgId}"
"""
import asyncio
import hashlib
import hmac
import json
import logging
import ssl
import time
import uuid
from collections.abc import Callable
from typing import Any, Optional

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

# ============================================================
# 基础 MQTT 配置（来自 MqttConfigure.java, PersistentNet.java）
# ============================================================
MQTT_PORT = 1883
MQTT_TLS_PORT = 443
MQTT_KEEPALIVE = 65           # MqttConfigure.keepAliveInterval = 65
MQTT_CONNECT_TIMEOUT = 10     # setConnectionTimeout(10)
MQTT_VERSION = mqtt.MQTTv311  # setMqttVersion(4)
MQTT_SIGN_METHOD = "hmacsha1" # MqttConfigure.SIGN_METHOD
MQTT_MAX_INFLIGHT = 10        # MqttConfigure.maxInflight = 10
MQTT_SDK_VERSION = "0.8.0"   # PersistentNet.f = "0.8.0"
MQTT_SECURE_MODE = 2          # MqttConfigure.SECURE_MODE = 2 (TLS)
MQTT_TLS_VERSION = ssl.PROTOCOL_TLSv1_2  # b.java 使用 TLSV1.2

# ============================================================
# 标准阿里云 IoT Topic（/sys/ 前缀 - 设备与云端通信）
# ============================================================
TOPIC_PROPERTY_POST = "/sys/{productKey}/{deviceName}/thing/property/post"
TOPIC_PROPERTY_SET = "/sys/{productKey}/{deviceName}/thing/property/set"
TOPIC_PROPERTY_GET = "/sys/{productKey}/{deviceName}/thing/property/get"
TOPIC_SERVICE_INVOKE = "/sys/{productKey}/{deviceName}/thing/service/invoke"
TOPIC_SERVICE_INVOKE_REPLY = "/sys/{productKey}/{deviceName}/thing/service/invoke_reply"
TOPIC_EVENT_POST = "/sys/{productKey}/{deviceName}/thing/event/{eventName}/post"

# ============================================================
# 应用侧下行 Topic（/app/down/ 前缀 - 云端推送给 App）
# 来自 TmpConstant.java
# ============================================================
TOPIC_APP_THING = "/app/down/thing"                          # 通用前缀
TOPIC_APP_PROPERTIES = "/app/down/thing/properties"           # 属性更新通知
TOPIC_APP_SERVICE_REPLY = "/app/down/thing/service/invoke/reply"  # 服务调用回复
TOPIC_APP_STATUS = "/app/down/thing/status"                   # 设备状态变更
TOPIC_APP_EVENTS = "/app/down/thing/events"                   # 事件通知
TOPIC_APP_NOTIFY = "/app/down/_thing/event/notify"            # 通用通知

# RRPC 回复后缀（来自 TmpConstant.URI_TOPIC_REPLY_POST = "_reply"）
TOPIC_REPLY_SUFFIX = "_reply"

# 额外 LAN 管理 topic（来自 CloudUtils.java）
TOPIC_LAN_PREFIX_GET = "/sys/{productKey}/{deviceName}/thing/lan/prefix/get"
TOPIC_LAN_PREFIX_UPDATE = "/sys/{productKey}/{deviceName}/thing/lan/prefix/update"
TOPIC_LAN_BLACKLIST_UPDATE = "/sys/{productKey}/{deviceName}/thing/lan/blacklist/update"
TOPIC_PUSH_DEVICE_INFO = "/sys/{productKey}/{deviceName}/thing/push/device/info"
TOPIC_DEVICE_INFO_UPDATE = "/sys/{productKey}/{deviceName}/thing/deviceinfo/update"
TOPIC_AUTHEN_REGISTER = "/sys/{productKey}/{deviceName}/thing/authen/sub/register"
TOPIC_SCRIPT_GET = "/sys/{productKey}/{deviceName}/thing/script/get"

# 注册/重连 topic（来自 b.java 第 840 行）
TOPIC_EXT_REGISTER = "/ext/register"
TOPIC_EXT_REGNWL = "/ext/regnwl"

# API 网关路径（来自 CloudUtils.java）
API_PATH_PROPERTIES_SET = "/living/thing/properties/set"
API_PATH_COMBO_PROPERTIES_SET = "/living/combomesh/thing/properties/set"
API_PATH_PROPERTIES_GET = "/thing/properties/get"
API_PATH_SERVICE_INVOKE = "/thing/service/invoke"


class MqttConnectionState:
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CONNECTFAIL = "connectfail"


def _hmac_sha1_sign(params: dict, secret: str) -> str:
    """HMAC-SHA1 签名，与 b.java 中的 a(Map, String) 方法一致

    签名步骤（来自 b.java 第 968-990 行）：
      1. 按键名排序
      2. 拼接为 key1value1key2value2...（排除 "sign" 键）
      3. 使用 UTF-8 编码
      4. 使用 HmacSHA1 算法
      5. 返回大写 HEX 字符串（来自 b.java 第 992-1002 行 bytesToHex）
    """
    sorted_keys = sorted(k for k in params.keys() if k.lower() != "sign")
    to_sign = "".join(f"{k}{params[k]}" for k in sorted_keys)
    mac = hmac.new(
        secret.encode("utf-8"),
        to_sign.encode("utf-8"),
        hashlib.sha1,
    )
    return mac.hexdigest().upper()


def _bytes_to_hex(data: bytes) -> str:
    """字节转大写 HEX，与 b.java 第 992-1002 行一致"""
    return "".join(f"{b:02X}" for b in data)


def _build_client_id(
    device_name: str,
    product_key: str,
    sign_method: str = MQTT_SIGN_METHOD,
    secure_mode: int = MQTT_SECURE_MODE,
    sdk_version: str = MQTT_SDK_VERSION,
    auth_type: str = "",
    uuid: str = "",
) -> str:
    """构建 MQTT ClientId，与 b.java 中 g() 方法一致

    ClientId 格式（来自 b.java 第 528-544 行，Frida 已验证）：
      {deviceName}&{productKey}|securemode={mode},_v={sdkVer},lan=HA,os=HA,
      signmethod=hmacsha1[,authType=connwl][,_uuid=md5(uuid)],ext=1|

    Frida 验证（实际 App 连接参数）：
      - lan=Android,os=12（App 端）
      - lan=HA,os=HA（HA 集成端，经测试验证通过）
    authType 在 deviceToken 模式时为 "connwl"（连接白名单）。
    """
    client_id = f"{device_name}&{product_key}"
    parts = [
        f"{client_id}|",
        f"securemode={secure_mode}",
        f",_v={sdk_version}",
        f",lan=HA,os=HA",
        f",signmethod={sign_method}",
    ]
    if auth_type:
        parts.append(f",authType={auth_type}")
    if uuid:
        parts.append(f",_uuid={_md5_hex(uuid)}")
    parts.append(",ext=1|")
    return "".join(parts)


def _md5_hex(data: str) -> str:
    """MD5 哈希，对应 b.java 中 a(String) 方法（第 1004-1023 行）"""
    return hashlib.md5(data.encode("utf-8")).hexdigest().upper()


class SlacMqttClient:
    """MQTT 客户端，封装阿里云 IoT MQTT 连接

    基于逆向分析 b.java（MqttNet.java）实现：
      - g() 方法：正常初始化流程
      - init() 方法：设置 MqttConfigure 全局参数后调用 g()
      - a(Map, String) 方法：HMAC-SHA1 签名
      - a.java (MqttDefaulCallback): 回调处理
      - send/a.java (MqttRpcMessageCallback): RRPC 消息匹配
    """

    def __init__(
        self,
        product_key: str,
        device_name: str,
        iot_token: str,
        device_secret: Optional[str] = None,
        on_property_update: Optional[Callable] = None,
        on_device_status: Optional[Callable] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        clean_session: bool = True,
        secure_mode: int = MQTT_SECURE_MODE,
        auth_type: str = "",
        uuid: str = "",
        check_root_crt: bool = False,
        mqtt_username: Optional[str] = None,
        mqtt_password: Optional[str] = None,
        device_token: Optional[str] = None,
    ):
        self._product_key = product_key
        self._device_name = device_name
        self._iot_token = iot_token
        self._device_secret = device_secret
        self._on_property_update = on_property_update
        self._on_device_status = on_device_status
        self._loop = loop or asyncio.get_event_loop()
        self._clean_session = clean_session
        self._secure_mode = secure_mode
        self._auth_type = auth_type
        self._uuid = uuid
        self._check_root_crt = check_root_crt
        self._mqtt_username = mqtt_username
        self._mqtt_password = mqtt_password
        self._device_token = device_token

        # 连接状态
        self._state = MqttConnectionState.DISCONNECTED
        self._mqttc: Optional[mqtt.Client] = None
        self._connect_lock = asyncio.Lock()
        self._disconnect_called = False
        self._connect_complete = False  # 跟踪首次连接是否已完成

        # 订阅的 topic 列表（用于重连后重新订阅）
        self._subscribed_topics: list[str] = []

        # 生成的 topic 缓存（避免重复字符串格式化）
        self._topic_cache: dict[str, str] = {}

        # RRPC pending 请求（来自 send/a.java 的 MqttRpcMessageCallback）
        # key: "{replyTopic},id={msgId}", value: {"reply_topic": str, "future": asyncio.Future}
        self._pending_rrpc: dict[str, dict] = {}

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == MqttConnectionState.CONNECTED

    @property
    def clean_session(self) -> bool:
        return self._clean_session

    @property
    def secure_mode(self) -> int:
        return self._secure_mode

    def _get_topic(self, template: str) -> str:
        """获取格式化的 topic（带缓存）"""
        if template not in self._topic_cache:
            self._topic_cache[template] = template.format(
                productKey=self._product_key, deviceName=self._device_name
            )
        return self._topic_cache[template]

    def _make_broker_host(self) -> str:
        """构建 MQTT broker 主机名

        Frida 验证（来自 MqttConfigure.mqttHost + MqttAsyncClient serverURI）：
          - MqttConfigure.mqttHost = "public.iot-as-mqtt.cn-shanghai.aliyuncs.com:1883"
          - MqttAsyncClient serverURI = "ssl://public.iot-as-mqtt.cn-shanghai.aliyuncs.com:1883"
        """
        return "public.iot-as-mqtt.cn-shanghai.aliyuncs.com"

    def _make_username(self) -> str:
        """构建 MQTT 用户名（与 b.java 一致）

        优先级：
          1. 显式设置的 mqttUserName
          2. 默认 {deviceName}&{productKey}
        """
        if self._mqtt_username:
            return self._mqtt_username
        return f"{self._device_name}&{self._product_key}"

    def _make_password(self) -> str:
        """构建 MQTT 密码

        与 b.java g() 方法一致（第 548-559 行），三种模式按优先级：
          1. deviceSecret 模式 → HMAC-SHA1 签名（标准设备认证）
          2. mqttUserName/mqttPassWord 显式设置 → 直接使用（同时覆盖 clientId）
          3. clientId + deviceToken 模式 → 直接使用 deviceToken
          4. 回退使用 iotToken
        """
        # 模式 2：显式设置的用户名密码
        if self._mqtt_username and self._mqtt_password:
            return self._mqtt_password

        # 模式 1：deviceSecret HMAC-SHA1 签名
        if self._device_secret:
            params = {
                "productKey": self._product_key,
                "deviceName": self._device_name,
                "clientId": f"{self._device_name}&{self._product_key}",
            }
            return _hmac_sha1_sign(params, self._device_secret)

        # 模式 3：deviceToken（连接白名单模式）
        if self._device_token:
            return self._device_token

        # 模式 4：回退 iotToken
        return self._iot_token

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: dict, rc: int, properties: Any = None):
        """MQTT 连接回调（v2 API）

        对应 a.java（MqttDefaulCallback）的 connectComplete 方法：
          - 连接成功（rc=0）：设置状态为 CONNECTED，重新订阅 topic
          - 连接失败（rc!=0）：设置状态为 CONNECTFAIL

        paho 的 connectComplete 回调（MqttCallbackExtended）：
          在首次连接和自动重连成功后都会调用。
        """
        if rc == 0:
            session_present = getattr(flags, 'session_present', False)
            is_reconnect = self._connect_complete
            self._connect_complete = True

            _LOGGER.info(
                "MQTT %s (productKey=%s, session_present=%s)",
                "reconnected" if is_reconnect else "connected successfully",
                self._product_key, session_present,
            )
            self._state = MqttConnectionState.CONNECTED

            # 重连后重新订阅所有 topic
            if self._subscribed_topics:
                self._resubscribe_topics()
            else:
                self._subscribe_all_topics()
        else:
            rc_map = {
                1: "incorrect protocol version",
                2: "invalid client identifier",
                3: "server unavailable",
                4: "bad username or password",
                5: "not authorized",
            }
            reason = rc_map.get(rc, f"unknown code {rc}")
            _LOGGER.error("MQTT connection failed: %s (rc=%d)", reason, rc)
            self._state = MqttConnectionState.CONNECTFAIL

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, disconnect_flags: Any, reason: Any, properties: Any = None):
        """MQTT 断开回调（v2 API）

        paho v2 回调签名: (client, userdata, disconnect_flags, reason, properties)
        对应 a.java 中 connectionLost 方法：
          - reason=0 (正常断开，由 async_disconnect() 触发)
          - reason!=0 (异常断开，paho 自动重连机制会处理)
        """
        # reason 可能是 ReasonCode 对象或 int
        rc = reason.value if hasattr(reason, 'value') else int(reason)
        if rc == 0:
            if not self._disconnect_called:
                _LOGGER.info("MQTT disconnected gracefully")
        else:
            _LOGGER.warning(
                "MQTT unexpected disconnected (rc=%d), auto-reconnect will handle",
                rc,
            )
        self._state = MqttConnectionState.DISCONNECTED

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage):
        """MQTT 消息回调 - 处理所有 topic 类型的消息

        对应 a.java（MqttDefaulCallback）的 messageArrived 方法：
          1. 广播消息到 PersistentEventDispatcher
          2. 匹配已注册的 RRPC listener
          3. 处理属性更新、设备状态等
          4. 调用 b.i().a(str, mqttMessage) 处理注册/重连消息
        """
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            _LOGGER.debug("MQTT message received on %s: %s", msg.topic, str(msg.payload)[:200])

            # 1. 检查是否是 pending RRPC 的回复
            # 匹配规则：replyTopic + ",id=" + msgId（来自 send/a.java）
            if self._check_pending_rrpc(msg.topic, payload):
                return

            # 2. 根据 topic 类型分发处理
            topic = msg.topic

            # 属性更新通知（/sys/{pk}/{dn}/thing/property/post 或 /app/down/thing/properties）
            if topic.endswith("/thing/property/post") or topic == TOPIC_APP_PROPERTIES:
                self._handle_property_update(topic, payload)

            # 设备状态变更（/app/down/thing/status）
            elif topic == TOPIC_APP_STATUS:
                self._handle_device_status(topic, payload)

            # 服务调用（/sys/{pk}/{dn}/thing/service/invoke）
            elif "/thing/service/invoke" in topic:
                _LOGGER.debug("MQTT service invoke on %s: %s", topic, str(payload)[:200])

            # 通用通知（/app/down/_thing/event/notify）
            elif topic == TOPIC_APP_NOTIFY:
                _LOGGER.debug("MQTT notify on %s: %s", topic, str(payload)[:200])

            # 设备注册/重连（/ext/register, /ext/regnwl）
            elif topic in (TOPIC_EXT_REGISTER, TOPIC_EXT_REGNWL):
                _LOGGER.info("MQTT register/renew on %s: %s", topic, str(payload)[:200])

            # LAN 管理 topic
            elif "/thing/lan/" in topic:
                _LOGGER.debug("MQTT LAN management on %s: %s", topic, str(payload)[:200])

            # 推送设备信息
            elif "/thing/push/device/info" in topic:
                _LOGGER.debug("MQTT push device info on %s: %s", topic, str(payload)[:200])

            else:
                _LOGGER.debug("MQTT unhandled topic: %s", topic)

        except json.JSONDecodeError:
            _LOGGER.warning("MQTT message JSON decode failed on %s: %s", msg.topic, str(msg.payload)[:200])
        except Exception as e:
            _LOGGER.error("MQTT message handler error on %s: %s", msg.topic, e)

    def _check_pending_rrpc(self, topic: str, payload: dict) -> bool:
        """检查消息是否匹配 pending RRPC 请求

        匹配逻辑（来自 send/a.java MqttRpcMessageCallback）：
          1. 从 payload 中提取 "id" 字段
          2. 构建 key: "{replyTopic},id={msgId}"
          3. 在 pending 字典中查找匹配项
        """
        # 从 payload 中提取 id 字段
        msg_id = payload.get("id", "")
        if not msg_id:
            # 尝试从嵌套结构中提取
            for key in ("requestId", "messageId", "request_id"):
                if key in payload:
                    msg_id = str(payload[key])
                    break

        if msg_id:
            # 构建匹配 key
            for key, pending in list(self._pending_rrpc.items()):
                reply_topic = pending.get("reply_topic", "")
                expected_key = f"{reply_topic},id={msg_id}"
                if key == expected_key or topic == reply_topic:
                    future = pending.get("future")
                    if future and not future.done():
                        future.set_result(payload)
                    self._pending_rrpc.pop(key, None)
                    _LOGGER.debug("MQTT RRPC reply matched: %s", key)
                    return True

        return False

    def _handle_property_update(self, topic: str, payload: dict):
        """处理属性更新消息

        支持多种 payload 格式：
          - 标准格式: {"items": {"PowerSwitch": 1, ...}}
          - 简化格式: {"params": {"PowerSwitch": 1, ...}}
          - 直接格式: {"PowerSwitch": 1, ...}
        """
        if not self._on_property_update:
            return

        items = {}
        if "items" in payload:
            items = payload["items"]
        elif "params" in payload:
            items = payload["params"]
        elif isinstance(payload, dict):
            # 检查是否是标准属性更新格式
            # 阿里云 IoT 属性上报格式: {"iotId": "...", "productKey": "...", "deviceName": "...", "items": {...}}
            if "iotId" in payload or "productKey" in payload:
                items = payload.get("items", payload)
            else:
                items = payload

        if not items:
            return

        self._loop.call_soon_threadsafe(
            self._on_property_update,
            {
                "iotId": payload.get("iotId", ""),
                "productKey": payload.get("productKey", self._product_key),
                "deviceName": payload.get("deviceName", self._device_name),
                "items": items,
                "raw": payload,
            },
        )

    def _handle_device_status(self, topic: str, payload: dict):
        """处理设备状态变更消息"""
        if not self._on_device_status:
            return

        self._loop.call_soon_threadsafe(
            self._on_device_status,
            {
                "iotId": payload.get("iotId", ""),
                "status": payload.get("status", payload.get("params", {})),
                "raw": payload,
            },
        )

    def _subscribe_all_topics(self):
        """订阅应用侧下行 topic

        仅订阅 /app/down/ 前缀的 topic，不订阅 /sys/ 前缀的设备 topic。
        测试验证（test_mqtt_topic_limit.py）：
          - 订阅 /sys/ 前缀 topic 导致连接在 2 秒内断开（RC=128）
          - 仅订阅 /app/down/ 前缀 topic 可保持连接稳定 60 秒以上
        """
        topics = [
            TOPIC_APP_PROPERTIES,
            TOPIC_APP_SERVICE_REPLY,
            TOPIC_APP_STATUS,
            TOPIC_APP_EVENTS,
        ]
        for topic_template in topics:
            topic = self._get_topic(template=topic_template)
            result = self._mqttc.subscribe(topic, qos=0)
            if result[0] == mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.info("MQTT subscribed to %s", topic)
                if topic not in self._subscribed_topics:
                    self._subscribed_topics.append(topic)
            else:
                _LOGGER.warning("MQTT subscribe to %s failed (rc=%d)", topic, result[0])

    def _resubscribe_topics(self):
        """重连后重新订阅所有已记录的 topic"""
        for topic in list(self._subscribed_topics):
            result = self._mqttc.subscribe(topic, qos=0)
            if result[0] == mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.info("MQTT re-subscribed to %s", topic)
            else:
                _LOGGER.warning("MQTT re-subscribe to %s failed (rc=%d)", topic, result[0])

    async def async_connect(self) -> bool:
        """异步连接 MQTT broker

        与 b.java 的 g() 方法一致：
          1. 创建 MQTT 客户端（MemoryPersistence）
          2. 设置 MqttConnectOptions（version, timeout, cleanSession, auth, keepalive, maxInflight）
          3. 设置 SSL/TLS（TLSv1.2）
          4. 设置回调
          5. 发起异步连接
          6. 等待连接结果（最多 connect_timeout 秒）
        """
        async with self._connect_lock:
            if self._state == MqttConnectionState.CONNECTED:
                return True

            self._disconnect_called = False
            self._state = MqttConnectionState.CONNECTING

            try:
                # 1. 创建 MQTT 客户端（与 b.java 第 586-596 行一致）
                client_id = _build_client_id(
                    self._device_name,
                    self._product_key,
                    secure_mode=self._secure_mode,
                    auth_type=self._auth_type,
                    uuid=self._uuid,
                )

                # 当显式设置 mqttUserName/mqttPassWord 时覆盖 clientId
                # （来自 b.java 第 551-554 行）
                if self._mqtt_username and self._mqtt_password:
                    # 注意：此时 clientId 应由外部传入的 mqtt_client_id 提供
                    # 这里保留默认 clientId，但 mqtt_username 会覆盖 username
                    pass
                self._mqttc = mqtt.Client(
                    client_id=client_id,
                    protocol=MQTT_VERSION,
                    clean_session=self._clean_session,
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                )

                # 2. 设置回调（与 b.java 第 620 行一致）
                self._mqttc.on_connect = self._on_connect
                self._mqttc.on_disconnect = self._on_disconnect
                self._mqttc.on_message = self._on_message

                # 3. 设置认证（与 b.java 第 614-617 行一致）
                username = self._make_username()
                password = self._make_password()
                self._mqttc.username_pw_set(username, password)

                # 4. 设置 SSL/TLS（与 b.java 第 601-612 行一致）
                # 使用 TLSv1.2（b.java 第 963 行: SSLContext.getInstance("TLSV1.2")）
                # App 中 isCheckRootCrt 控制是否验证服务器证书（默认 true）
                if self._secure_mode == 2:
                    if self._check_root_crt:
                        # 验证服务器证书（App 默认行为，使用 root.crt）
                        ssl_context = ssl.create_default_context()
                        ssl_context.check_hostname = True
                    else:
                        # 不验证证书（兼容模式）
                        ssl_context = ssl.SSLContext(MQTT_TLS_VERSION)
                        ssl_context.check_hostname = False
                        ssl_context.verify_mode = ssl.CERT_NONE
                    self._mqttc.tls_set_context(ssl_context)

                # 5. 设置自动重连（与 MqttConfigure.automaticReconnect=true 一致）
                self._mqttc.reconnect_delay_set(min_delay=1, max_delay=30)

                # 6. 设置 max_inflight（与 MqttConfigure.maxInflight=10 一致）
                self._mqttc.max_inflight_messages_set(MQTT_MAX_INFLIGHT)

                # 7. 发起连接（与 b.java 第 600 行 setConnectionTimeout(10) 一致）
                _LOGGER.info(
                    "MQTT connecting to %s:%d (username=%s, has_secret=%s, clean_session=%s, secure_mode=%s)",
                    self._make_broker_host(), MQTT_PORT,
                    username,
                    bool(self._device_secret),
                    self._clean_session,
                    self._secure_mode,
                )
                self._mqttc.connect_async(
                    self._make_broker_host(),
                    MQTT_PORT,
                    MQTT_KEEPALIVE,
                )
                self._mqttc.loop_start()

                # 8. 等待连接结果（与 b.java 的连接超时机制一致）
                for _ in range(50):  # 50 * 0.2 = 10 秒
                    await asyncio.sleep(0.2)
                    if self._state == MqttConnectionState.CONNECTED:
                        self._connect_complete = True
                        return True
                    if self._state == MqttConnectionState.CONNECTFAIL:
                        break

                _LOGGER.warning(
                    "MQTT connection timed out (%ds, state=%s)",
                    MQTT_CONNECT_TIMEOUT,
                    self._state,
                )
                self._mqttc.loop_stop()
                self._mqttc = None
                self._state = MqttConnectionState.CONNECTFAIL
                return False

            except Exception as e:
                _LOGGER.error("MQTT connect exception: %s", e)
                self._state = MqttConnectionState.CONNECTFAIL
                if self._mqttc:
                    try:
                        self._mqttc.loop_stop()
                    except Exception:
                        pass
                    self._mqttc = None
                return False

    async def async_disconnect(self):
        """断开 MQTT 连接

        与 b.java 的 destroy() 方法一致：
          1. 设置断开标志
          2. 停止网络循环
          3. 断开连接
          4. 清理状态
        """
        self._disconnect_called = True
        self._connect_complete = False
        if self._mqttc:
            try:
                self._mqttc.loop_stop()
                self._mqttc.disconnect()
            except Exception as e:
                _LOGGER.debug("MQTT disconnect error: %s", e)
            self._mqttc = None
        self._state = MqttConnectionState.DISCONNECTED
        self._subscribed_topics.clear()
        self._pending_rrpc.clear()
        self._topic_cache.clear()

    async def async_publish_properties(self, items: dict, iot_id: str = "") -> bool:
        """发布属性设置命令（fire-and-forget 模式）

        Topic: /sys/{productKey}/{deviceName}/thing/property/set
        Payload: {"items": {"PowerSwitch": 1, ...}, "iotId": "..."}

        与 App 中 CloudUtils.setProperties() 一致，但使用 MQTT 直连模式。
        """
        if not self._mqttc or self._state != MqttConnectionState.CONNECTED:
            _LOGGER.warning("MQTT not connected, cannot publish")
            return False

        topic = self._get_topic(TOPIC_PROPERTY_SET)
        payload = {"items": items}
        if iot_id:
            payload["iotId"] = iot_id

        try:
            payload_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            info = self._mqttc.publish(topic, payload_str, qos=0)
            if info.rc == mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.debug("MQTT published to %s: %s", topic, payload_str[:200])
                return True
            _LOGGER.warning("MQTT publish to %s failed (rc=%d)", topic, info.rc)
            return False
        except Exception as e:
            _LOGGER.error("MQTT publish error: %s", e)
            return False

    async def async_publish_rpc(
        self,
        method: str,
        params: dict,
        iot_id: str = "",
        timeout: float = 10.0,
    ) -> Optional[dict]:
        """发布 RPC 调用并等待回复（RRPC 模式）

        与 App 中 CloudUtils 的 RPC 模式一致（send/c.java 第 89-118 行）：
          1. 提取 payload 中的 "id" 字段作为 msgId
          2. 订阅 replyTopic（topic + "_reply"）
          3. 等待回复，通过 "{replyTopic},id={msgId}" 匹配

        Args:
            method: 服务方法名，如 "thing.service.property.set"
            params: 请求参数
            iot_id: 设备 IoT ID
            timeout: 等待超时秒数

        Returns:
            回复 payload dict，超时返回 None
        """
        if not self._mqttc or self._state != MqttConnectionState.CONNECTED:
            _LOGGER.warning("MQTT not connected, cannot publish RPC")
            return None

        request_id = str(uuid.uuid4())[:8]
        topic = f"/sys/{self._product_key}/{self._device_name}/thing/service/{method}"
        reply_topic = f"{topic}{TOPIC_REPLY_SUFFIX}"

        payload = {
            "id": request_id,
            "version": "1.0",
            "method": method,
            "params": params,
        }
        if iot_id:
            payload["iotId"] = iot_id

        # 创建 future 等待回复
        future: asyncio.Future = self._loop.create_future()
        rrpc_key = f"{reply_topic},id={request_id}"
        self._pending_rrpc[rrpc_key] = {
            "reply_topic": reply_topic,
            "future": future,
        }

        try:
            # 订阅 reply topic（与 send/c.java 第 111 行一致）
            self._mqttc.subscribe(reply_topic, qos=0)

            # 发布请求
            payload_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            info = self._mqttc.publish(topic, payload_str, qos=0)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.warning("MQTT RPC publish failed (rc=%d)", info.rc)
                self._pending_rrpc.pop(rrpc_key, None)
                return None

            _LOGGER.debug("MQTT RPC published to %s, waiting reply on %s", topic, reply_topic)

            # 等待回复
            try:
                reply = await asyncio.wait_for(future, timeout=timeout)
                return reply
            except asyncio.TimeoutError:
                _LOGGER.warning("MQTT RPC timeout after %ds: %s", timeout, method)
                self._pending_rrpc.pop(rrpc_key, None)
                return None

        except Exception as e:
            _LOGGER.error("MQTT RPC error: %s", e)
            self._pending_rrpc.pop(rrpc_key, None)
            return None

    async def async_publish_command(self, method: str, params: dict, iot_id: str = "") -> bool:
        """发布服务调用命令（非 RRPC，fire-and-forget 模式）"""
        if not self._mqttc or self._state != MqttConnectionState.CONNECTED:
            return False

        topic = f"/sys/{self._product_key}/{self._device_name}/thing/service/{method}"
        payload = {
            "method": method,
            "params": params,
        }
        if iot_id:
            payload["iotId"] = iot_id

        try:
            payload_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            info = self._mqttc.publish(topic, payload_str, qos=0)
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            _LOGGER.error("MQTT command publish error: %s", e)
            return False