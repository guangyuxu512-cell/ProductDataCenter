from app.modules.products.source_attributes import source_attributes


def test_reads_original_attribute_ids_and_multiple_values_without_duplicates():
    properties = {
        "501": [{"k": "材质", "value_name": "304 不锈钢", "value_id": "0"}],
        "502": [{"k": "适用场景", "value_name": "家用"}, {"k": "适用场景", "value_name": "户外"}],
    }
    formats = [{"format": [
        {"property_id": "501", "name": "材质", "message": [{"desc": "304 不锈钢"}]},
        {"property_id": "503", "name": "品牌", "message": [{"desc": "示例品牌"}]},
    ]}]
    assert source_attributes(properties, formats) == [
        {"id": "501", "name": "材质", "values": ["304 不锈钢"]},
        {"id": "502", "name": "适用场景", "values": ["家用", "户外"]},
        {"id": "503", "name": "品牌", "values": ["示例品牌"]},
    ]


def test_falls_back_to_product_format_without_fabricating_missing_values():
    formats = [{"format": [
        {"property_id": 123, "name": "材质", "message": [{"desc": "棉"}, {"desc": "棉"}]},
        {"property_id": "", "name": "货号", "message": [{"desc": "A001"}]},
        {"property_id": "9", "name": "品牌", "message": [{"desc": ""}]},
    ]}]
    assert source_attributes(None, formats) == [
        {"id": "123", "name": "材质", "values": ["棉"]},
        {"id": None, "name": "货号", "values": ["A001"]},
    ]
    assert source_attributes(None, None) == []


def test_conflicting_names_and_malformed_source_are_not_guessed():
    properties = {"1": [{"k": "材质", "value_name": "棉"}, {"k": "风格", "value_name": "简约"}],
                  "2": "invalid", "3": [{"k": "品牌", "value_name": {"nested": "not text"}}]}
    formats = [{"format": [{"property_id": "1", "name": "材质", "message": [{"desc": "棉"}]}]}]
    assert source_attributes(properties, formats) == []
