import esphome.codegen as cg
from esphome.components import ble_client

CODEOWNERS = ["@xiezhaoye"]
DEPENDENCIES = ["ble_client"]

treadmill_ns = cg.esphome_ns.namespace("treadmill")
TmDataHandler = treadmill_ns.class_("TmDataHandler", cg.Component)
