from copy import deepcopy

import pytest

from app.modules.products.jushuitan_legacy import prepare_legacy_category_repair


def test_repair_adds_source_and_target_without_losing_brand_or_packet():
    packet = {"goodsInfo": {"catId1": "1000009092", "catId2": "1000009147", "catId3": "0"},
              "category_properties_value": {"value": {"1687": [{"k": "品牌", "value_id": "596120136",
                                                                       "value_name": "无品牌"}]}},
              "goodsSkuInfo": {"original": True}}
    original = deepcopy(packet)
    source = [{"id": "50003449", "name": "砧板/菜板"}]
    target = [{"id": "1000009092", "name": "餐饮厨具"}, {"id": "1000009147", "name": "砧板/菜板"}]
    repaired = prepare_legacy_category_repair(packet, source, target)
    assert packet == original
    assert {k: v for k, v in repaired.items() if k not in {"douyinTarget", "_productDataCenterJushuitanSource"}} == original
    assert repaired["_productDataCenterJushuitanSource"]["category"] == source
    assert repaired["douyinTarget"]["category"] == target
    assert repaired["douyinTarget"]["attributes"]["1687"]["values"] == [{"valueId": "596120136", "name": "无品牌"}]
    with pytest.raises(ValueError, match="已变化"):
        prepare_legacy_category_repair(packet, source, [{"id": "1", "name": "错误类目"}])
    with pytest.raises(ValueError, match="拒绝覆盖"):
        prepare_legacy_category_repair(repaired, source, target)


def test_repair_refuses_attributes_that_cannot_be_uniquely_read():
    packet = {"goodsInfo": {"catId1": "100", "catId2": "0"},
              "category_properties_value": {"value": {"1": [
                  {"k": "旧名称", "value_name": "甲"}, {"k": "另一个名称", "value_name": "乙"}]}}}
    with pytest.raises(ValueError, match="无法完整读取"):
        prepare_legacy_category_repair(packet, [{"id": "500", "name": "来源"}], [{"id": "100", "name": "目标"}])
