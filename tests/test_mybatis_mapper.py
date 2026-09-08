"""MyBatis mapper model: `MyBatisMapperParser` (XML), `MyBatisExtractor`
(`@Select` annotations, via `JavaParser`), and `MyBatisResolver._assemble`.
"""

from pathlib import Path

from graph_rag.graph.mybatis_resolver import MyBatisResolver
from graph_rag.ingest.parsers.java_parser import JavaParser
from graph_rag.ingest.parsers.mybatis_mapper_parser import MyBatisMapperParser

_MAPPER_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE mapper PUBLIC "-//mybatis.org//DTD Mapper 3.0//EN"
    "http://mybatis.org/dtd/mybatis-3-mapper.dtd">
<mapper namespace="com.acme.orders.OrderMapper">

    <sql id="orderColumns">o.id, o.customer_id, o.status</sql>

    <select id="findById" resultType="Order">
        SELECT <include refid="orderColumns"/>
        FROM orders o
        <where>
            <if test="id != null">o.id = #{id}</if>
        </where>
    </select>

    <insert id="insert">
        INSERT INTO orders (customer_id, status) VALUES (#{customerId}, #{status})
    </insert>

    <update id="touchAudit">
        UPDATE order_audit SET touched_at = now() WHERE order_id = #{id}
    </update>
</mapper>
"""

_ANNOTATED_MAPPER = """\
package com.acme.orders;

import org.apache.ibatis.annotations.*;

@Mapper
public interface CustomerMapper {

    @Select("SELECT id, name FROM customers WHERE id = #{id}")
    Customer findById(long id);
}
"""


def _parse_xml(tmp_path: Path):
    path = tmp_path / "OrderMapper.xml"
    path.write_text(_MAPPER_XML)
    assert MyBatisMapperParser.can_handle(path) is True
    document = MyBatisMapperParser().parse(path)
    return {statement.statement_id: statement for statement in document.sql_statements}


def test_xml_namespace_and_id_bind_the_statement(tmp_path: Path) -> None:
    statements = _parse_xml(tmp_path)

    find = statements["findById"]
    assert find.mapper_qn == "com.acme.orders.OrderMapper"
    assert find.kind == "select"
    assert find.origin == "mybatis-xml"
    assert find.method_qn is None  # filled by the resolver


def test_xml_include_fragment_is_expanded_and_dynamic_tags_flattened(tmp_path: Path) -> None:
    statements = _parse_xml(tmp_path)

    text = statements["findById"].text
    assert "o.id, o.customer_id, o.status" in text  # <include refid="orderColumns">
    assert "<include" not in text and "<if" not in text
    assert "o.id = #{id}" in text  # <if> body kept


def test_xml_table_extraction_with_modes(tmp_path: Path) -> None:
    statements = _parse_xml(tmp_path)

    assert statements["findById"].tables == [{"name": "orders", "mode": "read"}]
    assert statements["insert"].tables == [{"name": "orders", "mode": "write"}]
    assert statements["touchAudit"].tables == [{"name": "order_audit", "mode": "write"}]


def test_select_annotation_variant_carries_its_method(tmp_path: Path) -> None:
    package_dir = tmp_path / "com" / "acme" / "orders"
    package_dir.mkdir(parents=True, exist_ok=True)
    path = package_dir / "CustomerMapper.java"
    path.write_text(_ANNOTATED_MAPPER)

    statements = JavaParser().parse(path).sql_statements

    assert len(statements) == 1
    statement = statements[0]
    assert statement.origin == "mybatis-annotation"
    assert statement.mapper_qn == "com.acme.orders.CustomerMapper"
    assert statement.method_qn == "com.acme.orders.CustomerMapper.findById(long)"
    assert statement.tables == [{"name": "customers", "mode": "read"}]


# -- MyBatisResolver._assemble --


def test_resolver_binds_xml_statement_to_the_matching_interface_method() -> None:
    statements = [
        {"id": "s1", "mapper_qn": "com.acme.orders.OrderMapper", "statement_id": "findById"}
    ]
    methods = [
        {
            "qn": "com.acme.orders.OrderMapper.findById(long)",
            "name": "findById",
            "owner": "com.acme.orders.OrderMapper",
        },
        {
            "qn": "com.acme.orders.CustomerMapper.findById(long)",
            "name": "findById",
            "owner": "com.acme.orders.CustomerMapper",
        },
    ]

    assembled = MyBatisResolver._assemble(statements, methods)

    assert assembled.executes == [
        {"method": "com.acme.orders.OrderMapper.findById(long)", "stmt": "s1"}
    ]


def test_resolver_leaves_an_unmatched_statement_unbound() -> None:
    statements = [{"id": "s1", "mapper_qn": "com.acme.NoSuchMapper", "statement_id": "gone"}]
    methods = [
        {"qn": "com.acme.orders.OrderMapper.findById(long)", "name": "findById", "owner": "x"}
    ]

    assembled = MyBatisResolver._assemble(statements, methods)

    assert assembled.executes == []
