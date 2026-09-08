package com.example.inventory;

import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface InventoryMapper {

    /** Bound by namespace + id to InventoryMapper.xml. */
    String findBySku(String sku);
}
