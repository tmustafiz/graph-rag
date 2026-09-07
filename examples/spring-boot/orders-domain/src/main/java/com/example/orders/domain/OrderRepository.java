package com.example.orders.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

/** Spring Data access to {@link Order} aggregates. */
public interface OrderRepository extends JpaRepository<Order, Long> {

    /** Derived query — parsed into the property paths customerId, status. */
    List<Order> findByCustomerIdAndStatusOrderByCreatedAtDesc(Long customerId, OrderStatus status);

    @Query("select o from Order o where size(o.lines) >= :minLines")
    List<Order> withAtLeastLines(@Param("minLines") int minLines);

    @Modifying
    @Query("update Order o set o.status = :status where o.id = :id")
    int updateStatus(@Param("id") Long id, @Param("status") OrderStatus status);
}
