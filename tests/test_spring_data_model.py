from pathlib import Path

from graph_rag.graph.spring_data_resolver import SpringDataResolver
from graph_rag.ingest.parsers import JavaParser

_ORDER_REPOSITORY = """\
package com.acme.order;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;

public interface OrderRepository extends JpaRepository<Order, Long> {

    List<Order> findByCustomerIdAndStatusOrderByCreatedAtDesc(Long customerId, String status);

    @Query("select o from Order o where o.total > :min")
    List<Order> bigOrders(double min);

    @Query(value = "SELECT * FROM orders WHERE status = ?1", nativeQuery = true)
    List<Order> rawByStatus(String status);

    @Modifying
    @Query("update Order o set o.status = 'CLOSED' where o.id = :id")
    int close(Long id);

    Order findById(Long id);

    List<Order> findBy();
}
"""

_ORDER_ENTITY = """\
package com.acme.order;

import java.util.List;
import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.Id;
import javax.persistence.ManyToOne;
import javax.persistence.OneToMany;
import javax.persistence.Table;

@Entity
@Table(name = "orders")
public class Order {

    @Id
    private Long id;

    @Column(name = "total_amount")
    private double total;

    @ManyToOne
    private Customer customer;

    @OneToMany(mappedBy = "order")
    private List<OrderLine> lines;
}
"""


def _parse(tmp_path: Path, name: str, body: str):
    path = tmp_path / name
    path.write_text(body)
    return JavaParser().parse(path)


def test_repository_entity_and_id_from_generics(tmp_path: Path) -> None:
    document = _parse(tmp_path, "OrderRepository.java", _ORDER_REPOSITORY)

    assert len(document.spring_data_repositories) == 1
    repo = document.spring_data_repositories[0]
    assert repo.qualified_name == "com.acme.order.OrderRepository"
    assert repo.base == "JpaRepository"
    assert repo.entity_type == "Order"
    assert repo.id_type == "Long"
    assert repo.reactive is False


def test_reactive_repository_flagged(tmp_path: Path) -> None:
    document = _parse(
        tmp_path,
        "DocRepository.java",
        "package com.acme;\n"
        "import org.springframework.data.repository.reactive.ReactiveCrudRepository;\n"
        "public interface DocRepository extends ReactiveCrudRepository<Doc, String> {}",
    )

    repo = document.spring_data_repositories[0]
    assert repo.reactive is True
    assert (repo.entity_type, repo.id_type) == ("Doc", "String")


def _methods(repo) -> dict[str, tuple[str, str]]:
    return {
        name: (kind, text)
        for name, kind, text in zip(
            repo.method_names, repo.method_query_kinds, repo.method_query_texts, strict=True
        )
    }


def test_query_kinds_captured(tmp_path: Path) -> None:
    document = _parse(tmp_path, "OrderRepository.java", _ORDER_REPOSITORY)
    methods = _methods(document.spring_data_repositories[0])

    assert methods["bigOrders"] == ("jpql", "select o from Order o where o.total > :min")
    assert methods["rawByStatus"][0] == "native"
    assert methods["rawByStatus"][1] == "SELECT * FROM orders WHERE status = ?1"
    assert methods["close"][0] == "modifying"
    assert methods["close"][1].startswith("update Order o")
    assert methods["findById"][0] == "inherited"
    assert methods["findByCustomerIdAndStatusOrderByCreatedAtDesc"][0] == "derived"


def test_derived_query_property_parse(tmp_path: Path) -> None:
    document = _parse(tmp_path, "OrderRepository.java", _ORDER_REPOSITORY)
    repo = document.spring_data_repositories[0]

    properties = dict(zip(repo.method_names, repo.method_properties, strict=True))
    assert properties["findByCustomerIdAndStatusOrderByCreatedAtDesc"] == "customerId,status"


def test_derived_property_with_and_or_letters_is_not_split(tmp_path: Path) -> None:
    document = _parse(
        tmp_path,
        "CatalogRepository.java",
        "package com.acme;\n"
        "import java.util.List;\n"
        "import org.springframework.data.repository.CrudRepository;\n"
        "public interface CatalogRepository extends CrudRepository<Item, Long> {\n"
        "  List<Item> findByOrderId(Long orderId);\n"
        "  List<Item> findByBrandNameAndOrgUnit(String brandName, String orgUnit);\n"
        "}",
    )
    repo = document.spring_data_repositories[0]
    properties = dict(zip(repo.method_names, repo.method_properties, strict=True))

    assert properties["findByOrderId"] == "orderId"
    assert properties["findByBrandNameAndOrgUnit"] == "brandName,orgUnit"


def test_unparseable_derived_name_does_not_raise(tmp_path: Path) -> None:
    document = _parse(
        tmp_path,
        "WeirdRepository.java",
        "package com.acme;\n"
        "import org.springframework.data.repository.CrudRepository;\n"
        "public interface WeirdRepository extends CrudRepository<Thing, Long> {\n"
        "  java.util.List<Thing> findByÿ();\n"
        "  java.util.List<Thing> totallyCustomName();\n"
        "}",
    )

    assert len(document.spring_data_repositories) == 1  # parsed, no exception


def test_no_repository_bean_is_not_emitted(tmp_path: Path) -> None:
    document = _parse(
        tmp_path,
        "BaseRepository.java",
        "package com.acme;\n"
        "import org.springframework.data.repository.NoRepositoryBean;\n"
        "import org.springframework.data.repository.Repository;\n"
        "@NoRepositoryBean\n"
        "public interface BaseRepository<T, ID> extends Repository<T, ID> {}",
    )

    assert document.spring_data_repositories == []


def test_jpa_entity_table_id_and_associations(tmp_path: Path) -> None:
    document = _parse(tmp_path, "Order.java", _ORDER_ENTITY)

    assert len(document.jpa_entities) == 1
    entity = document.jpa_entities[0]
    assert entity.qualified_name == "com.acme.order.Order"
    assert entity.kind == "entity"
    assert entity.table == "orders"
    assert entity.id_fields == ["id"]

    associations = {
        field: (kind, target, mapped_by)
        for field, kind, target, mapped_by in zip(
            entity.association_fields,
            entity.association_kinds,
            entity.association_targets,
            entity.association_mapped_by,
            strict=True,
        )
    }
    assert associations["customer"] == ("many-to-one", "Customer", "")
    assert associations["lines"] == ("one-to-many", "OrderLine", "order")


def test_embeddable_and_mapped_superclass_kinds(tmp_path: Path) -> None:
    document = _parse(
        tmp_path,
        "Audit.java",
        "package com.acme;\n"
        "import javax.persistence.MappedSuperclass;\n"
        "@MappedSuperclass\n"
        "public class Audit { }",
    )
    assert document.jpa_entities[0].kind == "mapped-superclass"


# -- SpringDataResolver._assemble (pure, no Neo4j) --


def _repo_def(**overrides):
    base = {
        "qualified_name": "com.acme.OrderRepository",
        "base": "JpaRepository",
        "entity_type": "Order",
        "id_type": "Long",
        "reactive": False,
        "method_qns": [],
        "method_query_kinds": [],
        "method_query_texts": [],
        "method_properties": [],
    }
    base.update(overrides)
    return base


def _entity_def(**overrides):
    base = {
        "qualified_name": "com.acme.Order",
        "simple_name": "Order",
        "kind": "entity",
        "table": "orders",
        "association_fields": [],
        "association_targets": [],
        "association_kinds": [],
        "association_mapped_by": [],
    }
    base.update(overrides)
    return base


def test_assemble_manages_resolves_entity_by_simple_name() -> None:
    assembled = SpringDataResolver._assemble(
        [_repo_def(entity_type="Order")],
        [_entity_def()],
        [
            {"qualified_name": "com.acme.Order", "name": "Order"},
            {"qualified_name": "com.acme.OrderRepository", "name": "OrderRepository"},
        ],
        [],
    )

    assert assembled.manages == [{"repo": "com.acme.OrderRepository", "entity": "com.acme.Order"}]
    assert assembled.repo_marks[0]["reactive"] is False


def test_assemble_persists_as_only_on_unambiguous_table_name() -> None:
    entity = _entity_def(table="orders")

    matched = SpringDataResolver._assemble(
        [],
        [entity],
        [{"qualified_name": "com.acme.Order", "name": "Order"}],
        [{"qualified_name": "sales.orders", "name": "orders"}],
    )
    assert matched.persists_as == [{"entity": "com.acme.Order", "table_qn": "sales.orders"}]

    ambiguous = SpringDataResolver._assemble(
        [],
        [entity],
        [{"qualified_name": "com.acme.Order", "name": "Order"}],
        [
            {"qualified_name": "sales.orders", "name": "orders"},
            {"qualified_name": "audit.orders", "name": "orders"},
        ],
    )
    assert ambiguous.persists_as == []


def test_assemble_relates_to_resolves_target_and_keeps_self_edges() -> None:
    order = _entity_def(
        qualified_name="com.acme.Order",
        simple_name="Order",
        association_fields=["lines", "parent"],
        association_targets=["OrderLine", "Order"],
        association_kinds=["one-to-many", "many-to-one"],
        association_mapped_by=["order", ""],
    )
    line = _entity_def(
        qualified_name="com.acme.OrderLine", simple_name="OrderLine", table="order_line"
    )

    assembled = SpringDataResolver._assemble(
        [],
        [order, line],
        [
            {"qualified_name": "com.acme.Order", "name": "Order"},
            {"qualified_name": "com.acme.OrderLine", "name": "OrderLine"},
        ],
        [],
    )

    assert assembled.relates_to == [
        {
            "from": "com.acme.Order",
            "to": "com.acme.OrderLine",
            "field": "lines",
            "kind": "one-to-many",
            "mapped_by": "order",
        },
        {
            "from": "com.acme.Order",
            "to": "com.acme.Order",
            "field": "parent",
            "kind": "many-to-one",
            "mapped_by": "",
        },
    ]


def test_assemble_method_marks_zip_repo_arrays() -> None:
    assembled = SpringDataResolver._assemble(
        [
            _repo_def(
                method_qns=["com.acme.OrderRepository.findByStatus(String)"],
                method_query_kinds=["derived"],
                method_query_texts=[""],
                method_properties=["status"],
            )
        ],
        [],
        [{"qualified_name": "com.acme.OrderRepository", "name": "OrderRepository"}],
        [],
    )

    assert assembled.method_marks == [
        {
            "qualified_name": "com.acme.OrderRepository.findByStatus(String)",
            "query_kind": "derived",
            "query_text": "",
            "query_properties": "status",
        }
    ]
