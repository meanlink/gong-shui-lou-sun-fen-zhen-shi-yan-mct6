"""分诊规则版本登记处。

升级算法时新增 src/rule_versions/rules_vN.py 并在 REGISTRY 登记，
已封存的旧版本文件永远不得修改；验真复算始终按凭据记录的 rule_version
取回对应版本独立执行，而不是调用当前 src.services.business。
"""
from src.rule_versions import rules_v1

# 每个版本对应一个不可变的独立计算包；当前生产算法的版本号由此声明。
CURRENT_RULE_VERSION = rules_v1.VERSION
REGISTRY = {rules_v1.VERSION: rules_v1}


def get_rule(version):
    """按版本号取回冻结的规则包；缺件时抛出 KeyError，由验真服务判失败。"""
    return REGISTRY[version]
