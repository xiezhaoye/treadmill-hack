import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import sensor, ble_client
from esphome.const import CONF_ID

from .. import treadmill_ns, TmDataHandler

DEPENDENCIES = ["ble_client"]

CONF_BLE_CLIENT_ID = "ble_client_id"
CONF_SPEED = "speed"
CONF_INCLINE = "incline"
CONF_DISTANCE = "distance"

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(TmDataHandler),
        cv.Required(CONF_BLE_CLIENT_ID): cv.use_id(ble_client.BLEClient),
        cv.Optional(CONF_SPEED): sensor.sensor_schema(
            unit_of_measurement="km/h",
            accuracy_decimals=2,
            icon="mdi:speedometer",
        ),
        cv.Optional(CONF_INCLINE): sensor.sensor_schema(
            unit_of_measurement="%",
            accuracy_decimals=1,
            icon="mdi:slope-uphill",
        ),
        cv.Optional(CONF_DISTANCE): sensor.sensor_schema(
            unit_of_measurement="m",
            accuracy_decimals=1,
            icon="mdi:map-marker-distance",
        ),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await ble_client.register_ble_node(var, config)

    # 头文件位置（相对 components/treadmill/）
    cg.add_global(
        cg.RawStatement(
            '#include "esphome/components/treadmill/sensor/tm_data_handler.h"'
        )
    )

    if CONF_SPEED in config:
        sens = await sensor.new_sensor(config[CONF_SPEED])
        cg.add(var.set_speed_sensor(sens))
    if CONF_INCLINE in config:
        sens = await sensor.new_sensor(config[CONF_INCLINE])
        cg.add(var.set_incline_sensor(sens))
    if CONF_DISTANCE in config:
        sens = await sensor.new_sensor(config[CONF_DISTANCE])
        cg.add(var.set_dist_sensor(sens))
