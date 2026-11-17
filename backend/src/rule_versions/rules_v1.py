"""冻结规则包 v1.0.0 —— 2026-11 基线分诊算法的独立可执行封存。

本模块是「可独立执行的计算依据」：
  * 不 import src.services.business，自身包含完整算法与输入校验；
  * 封存凭据(evidence)保存本文件源码与 SHA256 指纹，验真时比对指纹，
    任何对本文件的改动都会使历史凭据立即失效；
  * 算法升级只能新增 rules_vN.py，禁止改动本文件。
依赖口径固定：numpy 2.2.x / scikit-learn 1.6.x（见 backend/requirements.txt）。
"""
import numpy as np
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score, f1_score, confusion_matrix

VERSION = "v1.0.0"
FROZEN_AT = "2026-11-17"
RUNTIME = {"python": "3.12", "numpy": "2.2.6", "scikit-learn": "1.6.1"}

FEATURES = ["night_flow", "pressure_drop", "acoustic_db", "pipe_age"]
LABELS = ["夜间流量(m³/h)", "压力降(kPa)", "声学读数(dB)", "管龄(年)"]
METHOD = "分层70/30留出，random_state=42；Gini决策树按max_depth和min_samples_leaf剪枝；在留出集计算精确率、召回率和F1。"


def analyze(records, params):
    """与基线 analyze 完全同口径的独立实现，供验真复算调用。"""
    try:
        depth_raw = float(params.get("max_depth", 3))
        leaf_raw = float(params.get("min_leaf", 5))
        depth, leaf = int(depth_raw), int(leaf_raw)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("树深度与最小叶节点须为整数。") from exc
    if depth != depth_raw or leaf != leaf_raw or not 1 <= depth <= 8 or not 2 <= leaf <= 20:
        raise ValueError("树深度须为1~8，最小叶节点须为2~20，且都为整数。")
    if len(records) < 40:
        raise ValueError("至少需要40条管段复核样本。")
    try:
        x = np.asarray([[float(row[k]) for k in FEATURES] for row in records])
        y_raw = np.asarray([float(row["confirmed_leak"]) for row in records])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("管段字段必须完整且为数值。") from exc
    if not np.isfinite(x).all() or (x < 0).any() or not np.isin(y_raw, [0, 1]).all():
        raise ValueError("测量值须非负有限，复核标签须为0/1。")
    y = y_raw.astype(int)
    if np.bincount(y, minlength=2).min() < 8:
        raise ValueError("漏点与非漏点样本各至少8条。")
    train, valid = train_test_split(np.arange(len(y)), test_size=0.3, stratify=y, random_state=42)
    model = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=leaf, random_state=42)
    model.fit(x[train], y[train])
    probability = model.predict_proba(x[valid])[:, 1]
    prediction = model.predict(x[valid])
    precision = float(precision_score(y[valid], prediction, zero_division=0))
    recall = float(recall_score(y[valid], prediction, zero_division=0))
    f1 = float(f1_score(y[valid], prediction, zero_division=0))
    tn, fp, fn, tp = [int(v) for v in confusion_matrix(y[valid], prediction, labels=[0, 1]).ravel()]
    order = np.argsort(-probability)
    rows = [{"segment_id": str(records[int(valid[j])].get("segment_id", f"row-{int(valid[j])+1}")), "risk_pct": round(float(probability[j]) * 100, 1), "triage": "优先听漏复核" if prediction[j] else "常规巡查", "actual": "已确认漏点" if y[valid[j]] else "已确认正常"} for j in order]
    important = int(np.argmax(model.feature_importances_))
    first_rule = export_text(model, feature_names=FEATURES).splitlines()[0].strip()
    return {
        "summary": f"{len(train)}段训练、{len(valid)}段独立验证；实际树深{model.get_depth()}，生成{model.get_n_leaves()}个可复核叶节点。",
        "metrics": [{"label": "验证F1", "value": round(f1, 4)}, {"label": "漏点召回率", "value": round(recall * 100, 2), "unit": "%"}, {"label": "分诊精确率", "value": round(precision * 100, 2), "unit": "%"}, {"label": "验证漏检", "value": fn, "unit": "段"}],
        "table": {"columns": [{"key": "segment_id", "label": "管段"}, {"key": "risk_pct", "label": "叶节点漏点率(%)"}, {"key": "triage", "label": "分诊建议"}, {"key": "actual", "label": "留出集复核结果"}], "rows": rows},
        "chart": {"type": "bar", "labels": LABELS, "series": [{"name": "Gini分裂重要性", "values": [round(float(v), 4) for v in model.feature_importances_]}]},
        "findings": [f"验证混淆矩阵：命中漏点{tp}、误报{fp}、漏检{fn}、正确排除{tn}。", f"模型最重视{LABELS[important]}；根节点规则：{first_rule}。", "调高树深可能拟合局部噪声；只依据留出F1和漏检率选择规则复杂度。"],
        "method": METHOD, "warnings": ["分诊规则仅辅助现场巡检，不作为自动停水或施工决策。"],
    }
