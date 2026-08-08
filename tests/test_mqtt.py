"""
SLAC MQTT 测试脚本 - 测试 MQTT 客户端核心逻辑

测试范围：
1. _build_client_id() 函数 - ClientId 格式
2. _hmac_sha1_sign() 函数 - 签名算法
3. _md5_hex() 函数 - MD5 哈希
4. _make_password() 方法 - 密码生成
5. _make_username() 方法 - 用户名生成
6. _make_broker_host() 方法 - Broker 主机名
7. 模块导入和基本结构

注意：实际 MQTT 连接测试需要有效的 productKey/deviceName/deviceSecret。
如果 HA 服务器上已有 slac 配置，可以尝试获取凭据进行实际连接测试。
"""
import asyncio
import hashlib
import importlib
import importlib.util
import json
import logging
import sys
import os

# 直接加载 mqtt.py 模块，避免触发 slac 包的 __init__.py（依赖 homeassistant）
_mqtt_dir = os.path.join(os.path.dirname(__file__), "..", "custom_components", "slac")
_mqtt_spec = importlib.util.spec_from_file_location("slac_mqtt", os.path.join(_mqtt_dir, "mqtt.py"))
mqtt_mod = importlib.util.module_from_spec(_mqtt_spec)
_mqtt_spec.loader.exec_module(mqtt_mod)

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger("test_mqtt")

# ====== 单元测试部分 ======


def test_build_client_id():
    """测试 ClientId 构建"""
    _build_client_id = mqtt_mod._build_client_id
    _md5_hex = mqtt_mod._md5_hex

    # 测试基本格式
    client_id = _build_client_id(
        device_name="testDevice",
        product_key="testPK",
        secure_mode=2,
        sdk_version="0.8.0",
    )
    expected = "testDevice&testPK|securemode=2,_v=0.8.0,lan=HA,os=HA,signmethod=hmacsha1,ext=1|"
    assert client_id == expected, f"Basic format mismatch:\n  Got:      {client_id}\n  Expected: {expected}"
    print(f"[PASS] test_build_client_id (basic): {client_id[:60]}...")

    # 测试带 authType
    client_id = _build_client_id(
        device_name="testDevice",
        product_key="testPK",
        auth_type="connwl",
    )
    assert "authType=connwl" in client_id, "authType not found"
    print(f"[PASS] test_build_client_id (authType=connwl): {client_id[:60]}...")

    # 测试带 uuid
    client_id = _build_client_id(
        device_name="testDevice",
        product_key="testPK",
        uuid="test-uuid-123",
    )
    uuid_hash = _md5_hex("test-uuid-123")
    assert f"_uuid={uuid_hash}" in client_id, f"uuid hash not found: {uuid_hash}"
    print(f"[PASS] test_build_client_id (uuid): {uuid_hash} in client_id")

    # 测试同时带 authType 和 uuid
    client_id = _build_client_id(
        device_name="testDevice",
        product_key="testPK",
        auth_type="connwl",
        uuid="test-uuid-456",
    )
    assert "authType=connwl" in client_id
    uuid_hash = _md5_hex("test-uuid-456")
    assert f"_uuid={uuid_hash}" in client_id
    print(f"[PASS] test_build_client_id (authType+uuid): {client_id[:60]}...")


def test_hmac_sha1_sign():
    """测试 HMAC-SHA1 签名"""
    _hmac_sha1_sign = mqtt_mod._hmac_sha1_sign

    # 测试数据
    params = {
        "productKey": "testPK",
        "deviceName": "testDevice",
        "clientId": "testDevice&testPK",
    }
    secret = "testSecret"

    # 验证签名格式
    signature = _hmac_sha1_sign(params, secret)
    assert isinstance(signature, str), "Signature must be string"
    assert len(signature) == 40, f"HMAC-SHA1 must be 40 hex chars, got {len(signature)}"
    assert signature.isalnum(), "Signature must be hex"
    assert signature.isupper(), "Signature must be uppercase (per b.java)"

    # 验证可重复性
    sig2 = _hmac_sha1_sign(params, secret)
    assert signature == sig2, "Signature must be deterministic"

    # 验证不同 secret 生成不同签名
    sig3 = _hmac_sha1_sign(params, "differentSecret")
    assert signature != sig3, "Different secret must produce different signature"

    print(f"[PASS] test_hmac_sha1_sign: {signature}")


def test_md5_hex():
    """测试 MD5 哈希"""
    _md5_hex = mqtt_mod._md5_hex

    # 验证格式
    result = _md5_hex("test")
    assert isinstance(result, str)
    assert len(result) == 32
    assert result.isupper()

    # 验证正确性
    expected = hashlib.md5("test".encode("utf-8")).hexdigest().upper()
    assert result == expected

    print(f"[PASS] test_md5_hex: {result}")


def test_make_broker_host():
    """测试 Broker 主机名构建"""
    SlacMqttClient = mqtt_mod.SlacMqttClient

    # 模拟客户端
    client = SlacMqttClient(
        product_key="testPK",
        device_name="testDevice",
        iot_token="testToken",
        secure_mode=2,
    )

    host = client._make_broker_host()
    assert host == "public.iot-as-mqtt.cn-shanghai.aliyuncs.com"
    print(f"[PASS] test_make_broker_host: {host}")


def test_make_username():
    """测试用户名构建"""
    SlacMqttClient = mqtt_mod.SlacMqttClient

    # 默认模式
    client = SlacMqttClient(
        product_key="testPK",
        device_name="testDevice",
        iot_token="testToken",
    )
    username = client._make_username()
    assert username == "testDevice&testPK", f"Default username mismatch: {username}"
    print(f"[PASS] test_make_username (default): {username}")

    # 显式设置 mqtt_username
    client = SlacMqttClient(
        product_key="testPK",
        device_name="testDevice",
        iot_token="testToken",
        mqtt_username="customUser",
    )
    username = client._make_username()
    assert username == "customUser", f"Custom username mismatch: {username}"
    print(f"[PASS] test_make_username (custom): {username}")


def test_make_password():
    """测试密码生成（三种模式）"""
    SlacMqttClient = mqtt_mod.SlacMqttClient
    _hmac_sha1_sign = mqtt_mod._hmac_sha1_sign

    # 模式 1：deviceSecret HMAC-SHA1
    client = SlacMqttClient(
        product_key="testPK",
        device_name="testDevice",
        iot_token="fallbackToken",
        device_secret="testSecret",
    )
    password = client._make_password()
    expected = _hmac_sha1_sign(
        {"productKey": "testPK", "deviceName": "testDevice", "clientId": "testDevice&testPK"},
        "testSecret",
    )
    assert password == expected, f"DeviceSecret mode mismatch"
    print(f"[PASS] test_make_password (deviceSecret): {password[:20]}...")

    # 模式 2：mqttUserName/mqttPassWord 显式设置
    client = SlacMqttClient(
        product_key="testPK",
        device_name="testDevice",
        iot_token="fallbackToken",
        mqtt_username="customUser",
        mqtt_password="customPass",
    )
    password = client._make_password()
    assert password == "customPass", f"Explicit password mismatch: {password}"
    print(f"[PASS] test_make_password (explicit): {password}")

    # 模式 3：deviceToken
    client = SlacMqttClient(
        product_key="testPK",
        device_name="testDevice",
        iot_token="fallbackToken",
        device_token="deviceToken123",
    )
    password = client._make_password()
    assert password == "deviceToken123", f"DeviceToken mode mismatch: {password}"
    print(f"[PASS] test_make_password (deviceToken): {password}")

    # 模式 4：回退 iotToken
    client = SlacMqttClient(
        product_key="testPK",
        device_name="testDevice",
        iot_token="iotTokenFallback",
    )
    password = client._make_password()
    assert password == "iotTokenFallback", f"Fallback mismatch: {password}"
    print(f"[PASS] test_make_password (fallback): {password}")


def test_get_topic():
    """测试 Topic 缓存"""
    SlacMqttClient = mqtt_mod.SlacMqttClient
    TOPIC_PROPERTY_POST = mqtt_mod.TOPIC_PROPERTY_POST

    client = SlacMqttClient(
        product_key="testPK",
        device_name="testDevice",
        iot_token="testToken",
    )

    topic = client._get_topic(TOPIC_PROPERTY_POST)
    expected = "/sys/testPK/testDevice/thing/property/post"
    assert topic == expected, f"Topic mismatch: {topic} != {expected}"

    # 验证缓存
    topic2 = client._get_topic(TOPIC_PROPERTY_POST)
    assert topic == topic2, "Topic cache failed"

    print(f"[PASS] test_get_topic: {topic}")


def test_publish_properties():
    """测试属性发布（不发送，只验证参数构建）"""
    SlacMqttClient = mqtt_mod.SlacMqttClient

    client = SlacMqttClient(
        product_key="testPK",
        device_name="testDevice",
        iot_token="testToken",
    )

    # 测试未连接时的行为
    result = asyncio.run(client.async_publish_properties({"PowerSwitch": 1}, "iotId123"))
    assert result == False, "Should return False when not connected"

    print(f"[PASS] test_publish_properties (not connected): returns False")


def test_publish_rpc():
    """测试 RPC 发布（不发送，只验证参数构建）"""
    SlacMqttClient = mqtt_mod.SlacMqttClient

    _loop = asyncio.new_event_loop()
    client = SlacMqttClient(
        product_key="testPK",
        device_name="testDevice",
        iot_token="testToken",
        loop=_loop,
    )

    # 测试未连接时的行为
    result = asyncio.run(client.async_publish_rpc("thing.service.property.set", {"PowerSwitch": 1}))
    assert result is None, "Should return None when not connected"

    print(f"[PASS] test_publish_rpc (not connected): returns None")


def test_connection_state():
    """测试连接状态机"""
    SlacMqttClient = mqtt_mod.SlacMqttClient
    MqttConnectionState = mqtt_mod.MqttConnectionState

    _loop = asyncio.new_event_loop()
    client = SlacMqttClient(
        product_key="testPK",
        device_name="testDevice",
        iot_token="testToken",
        loop=_loop,
    )

    assert client.state == MqttConnectionState.DISCONNECTED
    assert not client.is_connected

    print(f"[PASS] test_connection_state: initial state = {client.state}")


# ====== 实际连接测试（需要有效凭据） ======


async def test_real_connect(creds: dict):
    """使用真实凭据测试 MQTT 连接

    需要从 HA 配置中获取的有效凭据：
    - productKey
    - deviceName
    - deviceSecret (可选)
    - iotToken
    """
    SlacMqttClient = mqtt_mod.SlacMqttClient

    product_key = creds.get("productKey")
    device_name = creds.get("deviceName")
    device_secret = creds.get("deviceSecret", "")
    iot_token = creds.get("iotToken", "")

    if not product_key or not device_name or not iot_token:
        _LOGGER.warning("Incomplete MQTT credentials, skipping real connection test")
        return False

    _LOGGER.info("Testing MQTT connection to %s...", product_key)

    client = SlacMqttClient(
        product_key=product_key,
        device_name=device_name,
        iot_token=iot_token,
        device_secret=device_secret or None,
        loop=asyncio.get_event_loop(),
        clean_session=True,
        secure_mode=2,
    )

    try:
        connected = await client.async_connect()
        if connected:
            _LOGGER.info("MQTT connected successfully!")
            _LOGGER.info("Subscribed topics: %s", client._subscribed_topics)
            await asyncio.sleep(5)  # 保持连接 5 秒观察消息
            await client.async_disconnect()
            _LOGGER.info("MQTT disconnected cleanly")
            return True
        else:
            _LOGGER.error("MQTT connection failed")
            return False
    except Exception as e:
        _LOGGER.error("MQTT connection error: %s", e)
        return False


# ====== 从 HA 服务器获取凭据 ======


async def get_credentials_from_ha():
    """通过 SSH 从 HA 服务器获取 slac 配置"""
    import subprocess

    cmd = (
        'ssh -i ~/.ssh/id_ha root@api.homediy.top '
        '"curl -s -H \\\"Authorization: Bearer $HA_TOKEN\\\" '
        '-H \\\"Content-Type: application/json\\\" '
        '\'http://localhost:8123/api/config_entries/entry\' | '
        'python3 -c \'import sys,json; '
        'data=json.load(sys.stdin); '
        'for e in data: '
        '  if e.get(\\\"domain\\\")==\\\"slac\\\": '
        '    d=e.get(\\\"data\\\",{}); '
        '    print(json.dumps({ '
        "      \\\"productKey\\\": d.get(\\\"mqtt_product_key\\\",\\\"\\\"),"
        "      \\\"deviceName\\\": d.get(\\\"mqtt_device_name\\\",\\\"\\\"),"
        "      \\\"deviceSecret\\\": d.get(\\\"mqtt_device_secret\\\",\\\"\\\"),"
        "      \\\"iotToken\\\": d.get(\\\"iot_token\\\",\\\"\\\"),"
        "      \\\"identityId\\\": d.get(\\\"identity_id\\\",\\\"\\\"),"
        "      \\\"refreshToken\\\": d.get(\\\"refresh_token\\\",\\\"\\\"),"
        "    }))\'"
    )

    try:
        result = subprocess.run(
            ["powershell", "-Command", cmd],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
        _LOGGER.warning("Failed to get credentials: %s", result.stderr[:200])
    except Exception as e:
        _LOGGER.warning("Error getting credentials: %s", e)
    return None


# ====== 主入口 ======


if __name__ == "__main__":
    print("=" * 60)
    print("SLAC MQTT 单元测试")
    print("=" * 60)

    # 运行单元测试
    tests = [
        test_build_client_id,
        test_hmac_sha1_sign,
        test_md5_hex,
        test_make_broker_host,
        test_make_username,
        test_make_password,
        test_get_topic,
        test_publish_properties,
        test_publish_rpc,
        test_connection_state,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"单元测试结果: {passed} passed, {failed} failed, {len(tests)} total")
    print(f"{'=' * 60}")

    if failed > 0:
        sys.exit(1)

    # 尝试获取 HA 凭据进行实际连接测试
    print("\n" + "=" * 60)
    print("尝试获取 HA 凭据进行实际 MQTT 连接测试...")
    print("=" * 60)

    creds = asyncio.run(get_credentials_from_ha())
    if creds:
        print(f"获取到凭据: productKey={creds.get('productKey')}, deviceName={creds.get('deviceName')}")
        result = asyncio.run(test_real_connect(creds))
        if result:
            print("\n实际 MQTT 连接测试: PASSED")
        else:
            print("\n实际 MQTT 连接测试: FAILED")
            sys.exit(1)
    else:
        print("无法获取 HA 凭据，跳过实际连接测试")
        print("提示: 如果没有实际凭据，可以:")
        print("  1. 部署到 HA 后观察日志")
        print("  2. 手动提供凭据进行测试")